"""
a WSGI server to serve PyPI compatible indexes and a full
recursive cache of pypi.python.org packages.
"""

import os, sys
import py
import threading
from logging import getLogger
log = getLogger(__name__)

import redis
from bottle import Bottle, response
from devpi_server.types import cached_property
from devpi_server.config import parseoptions

def main(argv=None):
    config = parseoptions(argv)
    xom = XOM(config)
    return bottle_run(xom)

class XOM:
    class Exiting(SystemExit):
        pass

    def __init__(self, config):
        self.config = config
        self._spawned = []
        self._shutdown = threading.Event()

    def shutdown(self):
        self._shutdown.set()

    def sleep(self, secs):
        if self._shutdown.wait(secs):
            raise self.Exiting()

    def spawn(self, func, args=(), kwargs={}):
        def logging_spawn():
            self._spawned.append(thread)
            log.debug("execution starts %s", func.__name__)
            try:
                func(*args, **kwargs)
            except self.Exiting:
                log.debug("received Exiting signal")
            finally:
                log.debug("execution finished %s", func.__name__)
            self._spawned.remove(thread)

        thread = threading.Thread(target=logging_spawn)
        thread.setDaemon(True)
        thread.start()
        return thread

    @cached_property
    def redis(self):
        import redis
        return redis.StrictRedis(port=self.config.args.redisport)

    @cached_property
    def releasefilestore(self):
        from devpi_server.filestore import ReleaseFileStore
        target = py.path.local(os.path.expanduser(self.config.args.datadir))
        return ReleaseFileStore(self.redis, target)

    @cached_property
    def extdb(self):
        from devpi_server.extpypi import ExtDB, HTMLCache
        htmlcache = HTMLCache(self.redis, self.httpget)
        return ExtDB(self.config.args.pypiurl, htmlcache,
                     self.releasefilestore)

    def httpget(self, url, allow_redirects):
        import requests.exceptions
        try:
            return requests.get(url, stream=True,
                                allow_redirects=allow_redirects)
        except requests.exceptions.RequestException:
            return FatalResponse(sys.exc_info())

    def create_app(self, catchall=True):
        from devpi_server.views import PyPIView, PkgView, route
        log.info("creating application in process %s", os.getpid())
        #start_background_tasks_if_not_in_arbiter(xom)
        app = Bottle(catchall=catchall)
        pypiview = PyPIView(self.extdb)
        route.discover_and_call(pypiview, app.route)
        pkgview = PkgView(self.releasefilestore, self.httpget)
        route.discover_and_call(pkgview, app.route)
        return app


class FatalResponse:
    status_code = -1

    def __init__(self, excinfo=None):
        self.excinfo = excinfo



# this flag indicates if we are running in the gunicorn master server
# if so, we don't start background tasks
workers = []

def post_fork(server, worker):
    # this hook is called by gunicorn in a freshly forked worker process
    workers.append(worker)
    log.debug("post_fork %s %s pid %s", server, worker, os.getpid())
    #log.info("vars %r", vars(worker))

def start_background_tasks_if_not_in_arbiter(xom):
    log.info("checking if running in worker %s", os.getpid())
    if not workers:
        return
    log.info("starting background tasks in pid %s", os.getpid())
    from devpi_server.extpypi import RefreshManager, XMLProxy
    xom.proxy = XMLProxy(xom.config.args.pypiurl + "pypi/")
    refresher = RefreshManager(xom.extdb, xom)
    xom.spawn(refresher.spawned_pypichanges,
              args=(xom.proxy, lambda: xom.sleep(5)))
    log.info("returning from background task starting")
    xom.spawn(refresher.spawned_refreshprojects,
              args=(lambda: xom.sleep(5),))

default_logging_config = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'standard': {
            'format': '%(asctime)s [%(levelname)-5.5s] %(name)s: %(message)s'
        },
    },
    'handlers': {
        'default': {
            'level':'DEBUG',
            'class':'logging.StreamHandler',
            'formatter': 'standard',
        },
    },
    'loggers': {
        '': {
            'handlers': ['default'],
            'level': 'DEBUG',
            'propagate': False,
        },
        'devpi_server': {
            'handlers': ['default'],
            'level': 'DEBUG',
            'propagate': False,
        },
    }
}

def bottle_run(xom):
    from logging.config import dictConfig
    dictConfig(default_logging_config)
    from bottle import run
    app = xom.create_app()
    workers.append(1)
    start_background_tasks_if_not_in_arbiter(xom)
    return app.run(reloader=False, debug=True, port=3141)
