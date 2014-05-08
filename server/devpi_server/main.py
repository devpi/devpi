# PYTHON_ARGCOMPLETE_OK
"""
a WSGI server to serve PyPI compatible indexes and a full
recursive cache of pypi.python.org packages.
"""
from __future__ import unicode_literals

import os, sys
import py
import threading
from logging import getLogger
log = getLogger(__name__)

from devpi_common.types import cached_property
from devpi_common.request import new_requests_session
from .config import parseoptions, configure_logging, load_setuptools_entrypoints
from .extpypi import XMLProxy
from . import __version__ as server_version


PYPIURL_XMLRPC = "https://pypi.python.org/pypi/"

class Fatal(Exception):
    pass

def fatal(msg):
    raise Fatal(msg)

def check_compatible_version(xom):
    args = xom.config.args
    if args.upgrade_state or args.export:
        return
    state_version = xom.get_state_version()
    if server_version != state_version:
        state_ver = map(int, state_version.split(".")[:2])
        server_ver = map(int, server_version.split(".")[:2])
        if state_ver != server_ver:
            fatal("Incompatible state: server %s cannot run serverdir "
                  "%s created by %s. "
                  "Use --export from older version, then --import with newer "
                  "version.  Or try --upgrade-state for in-place upgrades."
                  " But do a backup first :)"
                  %(server_version, xom.config.serverdir, state_version))

        xom.set_state_version(server_version)
        tw = py.io.TerminalWriter(sys.stderr)
        tw.line("minor version upgrade: setting serverstate to %s from %s" %(
                server_version, state_version), bold=True)

def main(argv=None, plugins=None):
    """ devpi-server command line entry point. """
    if plugins is None:
        plugins = []
    plugins.extend(load_setuptools_entrypoints())
    try:
        return _main(argv, plugins=plugins)
    except Fatal as e:
        tw = py.io.TerminalWriter(sys.stderr)
        tw.line("fatal: %s" %  e.args[0], red=True)
        return 1

def _main(argv=None, plugins=None):
    if argv is None:
        argv = sys.argv

    argv = [str(x) for x in argv]
    config = parseoptions(argv, plugins=plugins)
    args = config.args

    if args.version:
        print(server_version)
        return

    # meta commmands (that will not instantiate server object in-process)
    if args.gendeploy:
        from devpi_server.gendeploy import gendeploy
        return gendeploy(config)

    xom = XOM(config)
    check_compatible_version(xom)
    if args.start or args.stop or args.log or args.status:
        xprocdir = config.serverdir.join(".xproc")
        from devpi_server.bgserver import BackgroundServer
        tw = py.io.TerminalWriter()
        bgserver = BackgroundServer(tw, xprocdir)
        if args.start:
            return bgserver.start(args)
        elif args.stop:
            return bgserver.stop()
        elif args.log:
            return bgserver.log()
        elif args.status:
            if bgserver.info.isrunning():
                bgserver.line("server is running with pid %s" %
                              bgserver.info.pid)
            else:
                bgserver.line("no server is running")
            return

    if args.passwd:
        from devpi_server.db import run_passwd
        return run_passwd(xom.db, config.args.passwd)

    return xom.main()


def make_application():
    """ entry point for making an application object with defaults. """
    config = parseoptions([])
    return XOM(config).create_app()

def wsgi_run(xom):
    from wsgiref.simple_server import make_server
    app = xom.create_app(immediatetasks=True)
    host = xom.config.args.host
    port = xom.config.args.port
    log.info("devpi-server version: %s", server_version)
    log.info("serverdir: %s" % xom.config.serverdir)
    hostaddr = "http://%s:%s" % (host, port)
    log.info("serving at url: %s", hostaddr)
    log.info("bug tracker: https://bitbucket.org/hpk42/devpi/issues")
    log.info("IRC: #devpi on irc.freenode.net")
    if "WEBTRACE" in os.environ and xom.config.args.debug:
        from weberror.evalexception import make_eval_exception
        app = make_eval_exception(app, {})
    try:
        server = make_server(host, port, app)
    except Exception as e:
        log.exception("Error while starting the server.")
        return 1
    try:
        log.info("Hit Ctrl-C to quit.")
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


def add_keys(keyfs):
    # users and index configuration
    keyfs.USER = keyfs.addkey("{user}/.config", dict)

    # type pypimirror related data
    keyfs.PYPILINKS = keyfs.addkey("root/pypi/+links/{name}", dict)
    keyfs.PYPISERIALS = keyfs.addkey("root/pypi/+serials", dict)
    keyfs.PYPIFILE_NOMD5 = keyfs.addkey(
        "{user}/{index}/+e/{relpath}", bytes)
    keyfs.PYPISTAGEFILE = keyfs.addkey(
        "{user}/{index}/+f/{md5a}/{md5b}/{filename}", bytes)

    # type "stage" related
    keyfs.INDEXDIR = keyfs.addkey("{user}/{index}", "DIR")
    keyfs.PROJCONFIG = keyfs.addkey("{user}/{index}/{name}/.config", dict)
    keyfs.STAGEFILE = keyfs.addkey("{user}/{index}/+f/{md5}/{filename}", bytes)

    keyfs.STAGEDOCS = keyfs.addkey("{user}/{index}/{name}/{version}/+doc",
                                   "DIR")
    keyfs.RELDESCRIPTION = keyfs.addkey(
            "{user}/{index}/{name}/{version}/description_html", bytes)

    keyfs.PATHENTRY = keyfs.addkey("{relpath}-meta", dict)
    keyfs.ATTACHMENT = keyfs.addkey("+attach/{md5}/{type}/{num}", bytes)
    keyfs.FILEPATH = keyfs.addkey("{relpath}", bytes)

class XOM:
    class Exiting(SystemExit):
        pass

    def __init__(self, config, proxy=None, httpget=None):
        self.config = config
        self._spawned = []
        self._shutdown = threading.Event()
        self._shutdownfuncs = []
        if proxy is not None:
            self.proxy = proxy

        if httpget is not None:
            self.httpget = httpget
        sdir = config.serverdir
        if not (sdir.exists() and sdir.listdir()):
            self.set_state_version(server_version)

    def get_state_version(self):
        versionfile = self.config.serverdir.join(".serverversion")
        if not versionfile.exists():
            fatal("serverdir %s is unversioned, please use depvi-server-1.1 "
              "with the --upgrade-state option to upgrade from versions "
              "prior to 1.1\n" % self.config.serverdir)
        return versionfile.read()

    def set_state_version(self, version):
        versionfile = self.config.serverdir.join(".serverversion")
        versionfile.dirpath().ensure(dir=1)
        versionfile.write(version)

    def main(self):
        xom = self
        args = xom.config.args
        if args.upgrade_state:
            from devpi_server.importexport import do_upgrade
            return do_upgrade(xom)

        if args.export:
            from devpi_server.importexport import do_export
            return do_export(args.export, xom)
        configure_logging(xom.config)
        # access extdb to make sure invalidation happens
        xom.extdb
        if args.import_:
            from devpi_server.importexport import do_import
            return do_import(args.import_, xom)
        try:
            return wsgi_run(xom)
        finally:
            xom.shutdown()

    def fatal(self, msg):
        self.shutdown()
        fatal(msg)

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
    def filestore(self):
        from devpi_server.filestore import FileStore
        return FileStore(self.keyfs)

    @cached_property
    def keyfs(self):
        from devpi_server.keyfs import KeyFS
        keyfs = KeyFS(self.config.serverdir)
        add_keys(keyfs)
        return keyfs

    @cached_property
    def extdb(self):
        from devpi_server.extpypi import ExtDB
        extdb = ExtDB(keyfs=self.keyfs, httpget=self.httpget,
                      filestore=self.filestore,
                      proxy=self.proxy)
        return extdb

    @cached_property
    def proxy(self):
        return XMLProxy(PYPIURL_XMLRPC)

    @cached_property
    def db(self):
        from devpi_server.db import DB
        db = DB(self)
        set_default_indexes(db)
        return db

    @cached_property
    def _httpsession(self):
        session = new_requests_session(agent=("server", server_version))
        return session

    def httpget(self, url, allow_redirects, timeout=30):
        headers = {}
        USE_FRONT = self.config.args.bypass_cdn
        if USE_FRONT:
            log.debug("bypassing pypi CDN for: %s", url)
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
        except self._httpsession.RequestException:
            return FatalResponse(sys.exc_info())

    def create_app(self, immediatetasks=False):
        from pyramid.authentication import BasicAuthAuthenticationPolicy
        from pyramid.config import Configurator
        import functools
        log.debug("creating application in process %s", os.getpid())
        pyramid_config = Configurator()
        self.config.hook.devpiserver_pyramid_configure(
                config=self.config,
                pyramid_config=pyramid_config)
        pyramid_config.add_route("/+api", "/+api")
        pyramid_config.add_route("{path:.*}/+api", "{path:.*}/+api")
        pyramid_config.add_route("/+login", "/+login")
        pyramid_config.add_route("/+tests", "/+tests")
        pyramid_config.add_route("/+tests/{md5}/{type}", "/+tests/{md5}/{type}")
        pyramid_config.add_route("/+tests/{md5}/{type}/{num}", "/+tests/{md5}/{type}/{num}")
        pyramid_config.add_route("/{user}/{index}/+e/{relpath:.*}", "/{user}/{index}/+e/{relpath:.*}")
        pyramid_config.add_route("/{user}/{index}/+f/{relpath:.*}", "/{user}/{index}/+f/{relpath:.*}")
        pyramid_config.add_route("/{user}/{index}/+simple/", "/{user}/{index}/+simple/")
        pyramid_config.add_route("/{user}/{index}/+simple/{projectname}", "/{user}/{index}/+simple/{projectname}")
        pyramid_config.add_route("/{user}/{index}/{name}/{version}/+doc/{relpath:.*}", "/{user}/{index}/{name}/{version}/+doc/{relpath:.*}")
        pyramid_config.add_route("/{user}/{index}/{name}/{version}", "/{user}/{index}/{name}/{version}")
        pyramid_config.add_route("/{user}/{index}/{name}", "/{user}/{index}/{name}")
        pyramid_config.add_route("/{user}/{index}/", "/{user}/{index}/")
        pyramid_config.add_route("/{user}/{index}", "/{user}/{index}")
        pyramid_config.add_route("/{user}", "/{user}")
        pyramid_config.add_route("/", "/")
        # XXX hack for now until using proper Pyramid auth
        _get_credentials = BasicAuthAuthenticationPolicy._get_credentials
        # In Python 2 we need to get im_func, in Python 3 we already have
        # the correct value
        _get_credentials = getattr(_get_credentials, 'im_func', _get_credentials)
        pyramid_config.add_request_method(
            functools.partial(_get_credentials, None),
            name=str('auth'), property=True)
        # XXX end hack
        pyramid_config.scan()
        pyramid_config.registry['xom'] = self
        app = pyramid_config.make_wsgi_app()
        if immediatetasks == -1:
            pass
        else:
            plugin = BackgroundPlugin(xom=self)
            if immediatetasks:
                plugin.start_background_tasks()
            else:  # defer to when the first request arrives
                raise NotImplementedError
        return app

class BackgroundPlugin:
    api = 2
    name = "extdb_refresh"

    _thread = None

    def __init__(self, xom):
        self.xom = xom
        assert xom.proxy

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
        xom = self.xom
        self._thread = xom.spawn(xom.extdb.spawned_pypichanges,
            args=(xom.proxy, lambda: xom.sleep(xom.config.args.refresh)))

class FatalResponse:
    status_code = -1

    def __init__(self, excinfo=None):
        self.excinfo = excinfo

def set_default_indexes(db):
    PYPI = "root/pypi"
    if not db.index_exists(PYPI):
        if "root" not in db.user_list():
            db.user_create("root", password="")
        db.index_create(PYPI, bases=(), type="mirror", volatile=False)
        print("set root/pypi default index")

