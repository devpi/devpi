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
from .config import PluginManager
from .config import parseoptions, configure_logging, load_setuptools_entrypoints
from . import extpypi
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
    hook = PluginManager(plugins)
    try:
        return _main(argv, hook=hook)
    except Fatal as e:
        tw = py.io.TerminalWriter(sys.stderr)
        tw.line("fatal: %s" %  e.args[0], red=True)
        return 1

def _main(argv=None, hook=None):
    if argv is None:
        argv = sys.argv

    argv = [str(x) for x in argv]
    config = parseoptions(argv, hook=hook)
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
    configure_logging(config)
    extpypi.invalidate_on_version_change(xom.keyfs.basedir.join("root", "pypi"))

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
        from devpi_server.model import run_passwd
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
        log.exception("Error while starting the server: %s" %(e,))
        return 1
    try:
        log.info("Hit Ctrl-C to quit.")
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


def add_keys(keyfs):
    # users and index configuration
    keyfs.add_key("USER", "{user}/.config", dict)
    keyfs.add_key("USERLIST", ".config", set)

    # type pypimirror related data
    keyfs.add_key("PYPILINKS", "root/pypi/+links/{name}", dict)
    keyfs.add_key("PYPISERIALSPLITKEYS", "root/pypi/serials/+splitkeys", set)
    keyfs.add_key("PYPISERIALS", "root/pypi/serials/{splitkey}", dict)
    keyfs.add_key("PYPIFILE_NOMD5",
                 "{user}/{index}/+e/{dirname}/{basename}", bytes)
    keyfs.add_key("PYPISTAGEFILE",
                  "{user}/{index}/+f/{md5a}/{md5b}/{filename}", bytes)

    # type "stage" related
    keyfs.add_key("PROJCONFIG", "{user}/{index}/{name}/.config", dict)
    keyfs.add_key("PROJNAMES", "{user}/{index}/.projectnames", set)
    keyfs.add_key("STAGEFILE", "{user}/{index}/+f/{md5}/{filename}", bytes)

    keyfs.add_key("RELDESCRIPTION",
                  "{user}/{index}/{name}/{version}/description_html", bytes)

    keyfs.add_key("ATTACHMENT", "+attach/{md5}/{type}/{num}", bytes)
    keyfs.add_key("ATTACHMENTS", "+attach/.att", dict)
    # generic
    keyfs.add_key("PATHENTRY", "{relpath*}-meta", dict)
    keyfs.add_key("FILEPATH", "{relpath*}", bytes)

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
        set_default_indexes(self.model)

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

    @property
    def model(self):
        """ root model object. """
        from devpi_server.model import RootModel
        return RootModel(self)

    def main(self):
        xom = self
        args = xom.config.args
        if args.upgrade_state:
            from devpi_server.importexport import do_upgrade
            return do_upgrade(xom)

        if args.export:
            from devpi_server.importexport import do_export
            return do_export(args.export, xom)

        # need to initialize the pypi mirror state before importing
        # because importing may access data
        xom.pypimirror.init_pypi_mirror(self.proxy)
        if args.import_:
            from devpi_server.importexport import do_import
            return do_import(args.import_, xom)
        try:
            with xom.keyfs.transaction():
                results = xom.config.hook.devpiserver_run_commands(xom)
            if [x for x in results if x is not None]:
                errors = list(filter(None, results))
                if errors:
                    return errors[0]
                return 0

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
        self.addshutdownfunc("keyfs shutdown", keyfs.shutdown)
        return keyfs

    @cached_property
    def pypimirror(self):
        from devpi_server.extpypi import PrimaryMirror
        return PrimaryMirror(self.keyfs)

    @cached_property
    def proxy(self):
        return extpypi.XMLProxy(PYPIURL_XMLRPC)

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
        from devpi_server.views import route_url
        from pyramid.authentication import BasicAuthAuthenticationPolicy
        from pyramid.config import Configurator
        import functools
        log.debug("creating application in process %s", os.getpid())
        pyramid_config = Configurator()
        self.config.hook.devpiserver_pyramid_configure(
                config=self.config,
                pyramid_config=pyramid_config)
        pyramid_config.add_route("/+changelog", "/+changelog")
        pyramid_config.add_route("/+api", "/+api", accept="application/json")
        pyramid_config.add_route("{path:.*}/+api", "{path:.*}/+api", accept="application/json")
        pyramid_config.add_route("/+login", "/+login", accept="application/json")
        pyramid_config.add_route("/+tests", "/+tests", accept="application/json")
        pyramid_config.add_route("/+tests/{md5}/{type}", "/+tests/{md5}/{type}")
        pyramid_config.add_route("/+tests/{md5}/{type}/{num}", "/+tests/{md5}/{type}/{num}")
        pyramid_config.add_route("/{user}/{index}/+e/{relpath:.*}", "/{user}/{index}/+e/{relpath:.*}")
        pyramid_config.add_route("/{user}/{index}/+f/{relpath:.*}", "/{user}/{index}/+f/{relpath:.*}")
        pyramid_config.add_route("/{user}/{index}/+simple/", "/{user}/{index}/+simple/")
        pyramid_config.add_route("/{user}/{index}/+simple/{projectname}", "/{user}/{index}/+simple/{projectname:[^/]+/?}")
        pyramid_config.add_route("/{user}/{index}/{name}/{version}", "/{user}/{index}/{name}/{version:[^/]+/?}")
        pyramid_config.add_route(
            "simple_redirect", "/{user}/{index}/{name:[^/]+/?}",
            header="User-Agent:(distribute|setuptools|pip)/.*",
            accept="text/html",
        )
        pyramid_config.add_route("/{user}/{index}/{name}", "/{user}/{index}/{name:[^/]+/?}")
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
        # overwrite route_url method with our own
        pyramid_config.add_request_method(route_url)
        # XXX end hack
        pyramid_config.scan()
        pyramid_config.registry['xom'] = self
        app = pyramid_config.make_wsgi_app()
        if immediatetasks == -1:
            pass
        else:
            assert immediatetasks
            xom.spawn(xom.pypimirror.spawned_pypichanges,
                args=(xom.proxy, lambda: xom.sleep(xom.config.args.refresh)))
        return app


class FatalResponse:
    status_code = -1

    def __init__(self, excinfo=None):
        self.excinfo = excinfo

def set_default_indexes(model):
    with model.keyfs.transaction():
        root_user = model.get_user("root")
        if not root_user:
            root_user = model.create_user("root", "")
            print("created root user")
        userconfig = root_user.key.get()
        indexes = userconfig["indexes"]
        if "pypi" not in indexes:
            indexes["pypi"] = dict(bases=(), type="mirror", volatile=False)
            root_user.key.set(userconfig)
            print("created root/pypi index")
