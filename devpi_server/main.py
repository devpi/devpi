"""
a WSGI server to serve PyPI compatible indexes and a full
recursive cache of pypi.python.org packages.
"""

import os, sys
import py
import threading
from logging import getLogger
log = getLogger(__name__)

from pkg_resources import resource_string
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
        self._shutdownfuncs = []

    def shutdown(self):
        log.debug("shutting down")
        self._shutdown.set()
        for name, func in reversed(self._shutdownfuncs):
            log.info("shutdown: %s", name)
            func()
        log.debug("shutdown procedure finished")

    def addshutdownfunc(self, name, shutdownfunc):
        self._shutdownfuncs.append((name, shutdownfunc))

    def sleep(self, secs):
        self._shutdown.wait(secs)
        if self._shutdown.is_set():
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

    def startprocess(self, name, preparefunc, restart=True):
        pid, logfile = self._xprocess.ensure(name, preparefunc,
                                             restart=restart)
        def killproc():
            try:
                py.process.kill(pid)
            except OSError:
                pass
        self.addshutdownfunc("kill %s server pid %s" % (name, pid), killproc)
        return pid, logfile

    @cached_property
    def _xprocess(self):
        from devpi_server.vendor.xprocess import XProcess
        return XProcess(self.config, self.datadir, log=log)


    @cached_property
    def redis(self):
        import redis
        client = redis.StrictRedis(port=self.config.args.redisport)
        return client

    @cached_property
    def datadir(self):
        return py.path.local(os.path.expanduser(self.config.args.datadir))


    @cached_property
    def releasefilestore(self):
        from devpi_server.filestore import ReleaseFileStore
        return ReleaseFileStore(self.redis, self.datadir)

    @cached_property
    def extdb(self):
        from devpi_server.extpypi import ExtDB, HTMLCache
        htmlcache = HTMLCache(self.redis, self.httpget)
        return ExtDB(self.config.args.pypiurl, htmlcache,
                     self.releasefilestore)

    @cached_property
    def _httpsession(self):
        import requests
        return requests.session()

    def httpget(self, url, allow_redirects):
        from requests.exceptions import RequestException
        try:
            return self._httpsession.get(url, stream=True,
                                         allow_redirects=allow_redirects)
        except RequestException:
            return FatalResponse(sys.exc_info())

    def create_app(self, catchall=True):
        from devpi_server.views import PyPIView, PkgView, route
        from bottle import Bottle
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
    log.debug("checking if running in worker %s", os.getpid())
    if not workers:
        return
    log.info("starting background tasks from process %s", os.getpid())
    if xom.config.args.redismode == "auto":
        start_redis_server(xom)
    from devpi_server.extpypi import RefreshManager, XMLProxy
    xom.proxy = XMLProxy(xom.config.args.pypiurl + "pypi/")
    refresher = RefreshManager(xom.extdb, xom)
    xom.spawn(refresher.spawned_pypichanges,
              args=(xom.proxy, lambda: xom.sleep(xom.config.args.refresh)))
    log.debug("returning from background task starting")
    xom.spawn(refresher.spawned_refreshprojects,
              args=(lambda: xom.sleep(5),))

def start_redis_server(xom):
    from devpi_server.config import configure_redis_start
    port = xom.config.args.redisport
    prepare_redis = configure_redis_start(port)
    pid, logfile = xom.startprocess("redis", prepare_redis)
    log.info("started redis-server pid %s on port %s", pid, port)


def get_logging_config(debug=True):
    if debug:
        loglevel = "DEBUG"
    else:
        loglevel = "INFO"

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
                'level': loglevel,
                'class':'logging.StreamHandler',
                'formatter': 'standard',
            },
        },
        'loggers': {
            '': {
                'handlers': ['default'],
                'level': loglevel,
                'propagate': False,
            },
            'devpi_server': {
                'handlers': ['default'],
                'level': loglevel,
                'propagate': False,
            },
        }
    }
    return default_logging_config

def bottle_run(xom):
    from logging.config import dictConfig
    dictConfig(get_logging_config(xom.config.args.debug))
    from bottle import run
    app = xom.create_app()
    workers.append(1)
    start_background_tasks_if_not_in_arbiter(xom)
    ret = app.run(reloader=False, port=3141)
    xom.shutdown()
    return ret
