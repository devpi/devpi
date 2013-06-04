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

def add_keys(keyfs):
    # users and index configuration
    keyfs.USER = keyfs.addkey("{user}/.config", dict)

    # type pypimirror related data
    keyfs.PYPILINKS = keyfs.addkey("root/pypi/links/{name}", list)
    keyfs.PYPIFILES = keyfs.addkey("root/pypi/c/{relpath}", file)
    keyfs.PYPISERIAL = keyfs.addkey("root/pypi/serial", int)
    keyfs.PYPIINVALID = keyfs.addkey("root/pypi/invalid", dict)

    # type stage related
    keyfs.STAGELINKS = keyfs.addkey("{user}/{index}/links/{name}", dict)
    keyfs.STAGEFILE = keyfs.addkey("{user}/{index}/f/{md5}/{filename}", bytes)
    keyfs.PATHENTRY = keyfs.addkey("{relpath}-meta", dict)
    keyfs.FILEPATH = keyfs.addkey("{relpath}", bytes)

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

    @cached_property
    def datadir(self):
        return py.path.local(os.path.expanduser(self.config.args.datadir))

    @cached_property
    def releasefilestore(self):
        from devpi_server.filestore import ReleaseFileStore
        return ReleaseFileStore(self.keyfs)

    @cached_property
    def keyfs(self):
        from devpi_server.keyfs import KeyFS
        keyfs = KeyFS(self.datadir)
        add_keys(keyfs)
        return keyfs

    @cached_property
    def extdb(self):
        from devpi_server.extpypi import ExtDB
        return ExtDB(xom=self)

    @cached_property
    def db(self):
        from devpi_server.db import DB
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
    config = parseoptions()
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
    from devpi_server.extpypi import RefreshManager, XMLProxy
    from xmlrpclib import ServerProxy
    xom.proxy = XMLProxy(ServerProxy(PYPIURL_XMLRPC))
    refresher = RefreshManager(xom.extdb, xom)
    xom.spawn(refresher.spawned_pypichanges,
              args=(xom.proxy, lambda: xom.sleep(xom.config.args.refresh)))
    log.debug("returning from background task starting")
    xom.spawn(refresher.spawned_refreshprojects,
              args=(lambda: xom.sleep(5),))

def bottle_run(xom):
    workers.append(1)
    start_background_tasks_if_not_in_arbiter(xom)
    app = xom.create_app(catchall=not xom.config.args.debug)
    port = xom.config.args.port
    log.info("devpi-server version: %s", devpi_server.__version__)
    log.info("serving index url: http://%s:%s/ext/pypi/simple/",
             xom.config.args.host, xom.config.args.port)
    log.info("bug tracker: https://bitbucket.org/hpk42/devpi-server/issues")
    log.info("IRC: #pylib on irc.freenode.net")
    ret = app.run(server=xom.config.args.bottleserver,
                  host=xom.config.args.host,
                  reloader=False, port=port)
    xom.shutdown()
    return ret

def set_default_indexes(db):
    PROD = "root/prod"
    PYPI = "root/pypi"
    DEV = "root/dev"
    if "root" not in db.user_list():
        db.user_setpassword("root", "")
    db.user_indexconfig_set(PYPI, bases=(), type="mirror", volatile=False)
    db.user_indexconfig_set(PROD, bases=(), type="stage", volatile=False)
    db.user_indexconfig_set(DEV, bases=(PROD,), type="stage", volatile=True)
