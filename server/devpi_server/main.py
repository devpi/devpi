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

USE_FRONT = 1  # use front.pypi.org for getting simple pages


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

def make_application():
    """ entry point for making an application object with defaults. """
    config = parseoptions([])
    return XOM(config).create_app()

def bottle_run(xom):
    import bottle
    app = xom.create_app(immediatetasks=True,
                         catchall=not xom.config.args.debug)
    port = xom.config.args.port
    log.info("devpi-server version: %s", devpi_server.__version__)
    log.info("serving at url: http://%s:%s/",
             xom.config.args.host, xom.config.args.port)
    log.info("bug tracker: https://bitbucket.org/hpk42/devpi/issues")
    log.info("IRC: #pylib on irc.freenode.net")
    if xom.config.args.debug:
        from weberror.evalexception import make_eval_exception
        app = make_eval_exception(app, {})
    ret = bottle.run(app=app, server=xom.config.args.bottleserver,
                  host=xom.config.args.host,
                  reloader=False, port=port)
    xom.shutdown()
    return ret

def add_keys(keyfs):
    # users and index configuration
    keyfs.USER = keyfs.addkey("{user}/.config", dict)

    # type pypimirror related data
    keyfs.PYPILINKS = keyfs.addkey("root/pypi/links/{name}", list)
    keyfs.PYPIFILES = keyfs.addkey("root/pypi/f/{relpath}", file)
    keyfs.PYPISERIALS = keyfs.addkey("root/pypi/serials", dict)

    # type "stage" related
    keyfs.INDEXDIR = keyfs.addkey("{user}/{index}", "DIR")
    keyfs.PROJCONFIG = keyfs.addkey("{user}/{index}/{name}/.config", dict)
    keyfs.STAGEFILE = keyfs.addkey(
            "{user}/{index}/{proj}/{version}/{filename}", bytes)
    keyfs.STAGEDOCS = keyfs.addkey("{user}/{index}/{name}/.doc", "DIR")

    keyfs.RELDESCRIPTION = keyfs.addkey(
            "{user}/{index}/{name}/{version}/description_html", bytes)
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
        headers = {}
        if USE_FRONT:
            if url.startswith("https://pypi.python.org/simple/"):
                url = url.replace("https://pypi", "https://front")
                headers["HOST"] = "pypi.python.org"
        try:
            resp = self._httpsession.get(url, stream=True,
                                         allow_redirects=allow_redirects,
                                         headers=headers,
                                         timeout=timeout)
            if USE_FRONT and resp.url.startswith("https://front.python.org"):
                resp.url = resp.url.replace("https://front.python.org",
                                            "https://pypi.python.org")
            return resp
        except RequestException:
            return FatalResponse(sys.exc_info())

    def create_app(self, catchall=True, immediatetasks=False):
        from devpi_server.views import PyPIView, route
        from bottle import Bottle
        log.info("creating application in process %s", os.getpid())
        app = Bottle(catchall=catchall)
        plugin = BackgroundPlugin(xom=self)
        if immediatetasks == -1:
            pass
        elif immediatetasks:
            plugin.start_background_tasks()
        else:  # defer to when the first request arrives
            app.install(plugin)
        pypiview = PyPIView(self)
        route.discover_and_call(pypiview, app.route)
        return app

class BackgroundPlugin:
    api = 2
    name = "extdb_refresh"

    _thread = None

    def __init__(self, xom):
        self.xom = xom

    def setup(self, app):
        log.debug("plugin.setup(%r)", app)
        self.app = app

    def apply(self, callback, route):
        log.debug("plugin.apply() with %r, %r", callback, route)
        def mywrapper(*args, **kwargs):
            if not self._thread:
                self.start_background_tasks()
                self.app.uninstall(self)
            return callback(*args, **kwargs)
        return mywrapper

    def close(self):
        log.debug("plugin.close() called")

    def start_background_tasks(self):
        from devpi_server.extpypi import XMLProxy
        from xmlrpclib import ServerProxy
        xom = self.xom
        PYPIURL_XMLRPC = "https://pypi.python.org/pypi/"
        xom.proxy = XMLProxy(ServerProxy(PYPIURL_XMLRPC))
        self._thread = xom.spawn(xom.extdb.spawned_pypichanges,
            args=(xom.proxy, lambda: xom.sleep(xom.config.args.refresh)))

class FatalResponse:
    status_code = -1

    def __init__(self, excinfo=None):
        self.excinfo = excinfo


def set_default_indexes(db):
    PYPI = "root/pypi"
    DEV = "root/dev"
    if "root" not in db.user_list():
        db.user_setpassword("root", "")
    db.user_indexconfig_set(PYPI, bases=(), type="mirror", volatile=False)
    db.user_indexconfig_set(DEV, bases=(PYPI,), type="stage", volatile=True)
