"""
a WSGI server to serve PyPI compatible indexes and a full
recursive cache of pypi.python.org packages.
"""

import os, sys
import py
import threading
from logging import getLogger
log = getLogger(__name__)

from devpi_server.types import cached_property
from devpi_server.config import parseoptions, configure_logging
import devpi_server

PYPIURL_XMLRPC = "https://pypi.python.org/pypi/"

def main(argv=None):
    """ devpi-server command line entry point. """
    config = parseoptions(argv)
    if config.args.version:
        print (devpi_server.__version__)
        return


    if config.args.gendeploy:
        from devpi_server.gendeploy import gendeploy
        return gendeploy(config)

    configure_logging(config)
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
        log.debug("appending shutdown func %s", name)
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

    def startprocess(self, name, preparefunc, restart=False):
        pid, logfile = self._xprocess.ensure(name, preparefunc,
                                             restart=restart)
        #log.info("logfile %s", logfile.name)
        #log.info("logfile content %r", open(logfile.name).read())
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
        #self.addshutdownfunc("shutdown redis", client.shutdown)
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
        from devpi_server.extpypi import ExtDB
        return ExtDB(xom=self)

    @cached_property
    def db(self):
        from devpi_server.db import DB, set_default_indexes
        db = DB(self)
        set_default_indexes(db)
        return db

    @cached_property
    def _httpsession(self):
        import requests
        return requests.session()

    def httpget(self, url, allow_redirects, timeout=30):
        from requests.exceptions import RequestException
        try:
            return self._httpsession.get(url, stream=True,
                                         allow_redirects=allow_redirects,
                                         timeout=timeout)
        except RequestException:
            return FatalResponse(sys.exc_info())

    def create_app(self, catchall=True):
        from devpi_server.views import PyPIView, PkgView, route
        from bottle import Bottle
        log.info("creating application in process %s", os.getpid())
        app = Bottle(catchall=catchall)
        pypiview = PyPIView(self)
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

def make_application():
    ### unused function for creating an app
    config = parseoptions(["--redismode=manual", "--redisport=6379"])
    xom = XOM(config)
    start_background_tasks_if_not_in_arbiter(xom)
    app = xom.create_app()
    return app

def application(environ, start_response, app=[]):
    """ entry point for wsgi-servers who need an application object
    in a module. """
    if not app:
        app.append(make_application())
    return app[0](environ, start_response)

def start_background_tasks_if_not_in_arbiter(xom):
    log.debug("checking if running in worker %s", os.getpid())
    if not workers:
        return
    log.info("starting background tasks from process %s", os.getpid())
    if xom.config.args.redismode == "auto":
        start_redis_server(xom)
    from devpi_server.extpypi import RefreshManager, XMLProxy
    from xmlrpclib import ServerProxy
    xom.proxy = XMLProxy(ServerProxy(PYPIURL_XMLRPC))
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

def bottle_run(xom):
    workers.append(1)
    start_background_tasks_if_not_in_arbiter(xom)
    app = xom.create_app(catchall=not xom.config.args.debug)
    port = xom.config.args.port
    log.info("devpi-server version: %s", devpi_server.__version__)
    log.info("serving index url: http://localhost:%s/ext/pypi/simple/",
             xom.config.args.port)
    log.info("bug tracker: https://bitbucket.org/hpk42/devpi-server/issues")
    log.info("IRC: #pylib on irc.freenode.net")
    ret = app.run(server=xom.config.args.bottleserver,
                  reloader=False, port=port)
    xom.shutdown()
    return ret
