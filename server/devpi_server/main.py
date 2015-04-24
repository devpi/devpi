# PYTHON_ARGCOMPLETE_OK
"""
a WSGI server to serve PyPI compatible indexes and a full
recursive cache of pypi.python.org packages.
"""
from __future__ import unicode_literals

import os, sys
import py

from devpi_common.types import cached_property
from devpi_common.request import new_requests_session
from .config import PluginManager
from .config import parseoptions, load_setuptools_entrypoints
from .log import configure_logging, threadlog
from .model import BaseStage
from . import extpypi, replica, mythread
from . import __version__ as server_version


PYPIURL_XMLRPC = "https://pypi.python.org/pypi/"

class Fatal(Exception):
    pass

def fatal(msg):
    raise Fatal(msg)

def check_compatible_version(xom):
    args = xom.config.args
    if args.export:
        return
    state_version = xom.get_state_version()
    if server_version != state_version:
        state_ver = state_version.split(".")
        server_ver = server_version.split(".")
        if state_ver[:2] != server_ver[:2]:
            fatal("Incompatible state: server %s cannot run serverdir "
                  "%s created by %s.\n"
                  "Use --export from older version, then --import with newer "
                  "version."
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
    # Set up logging with no config just so we can log while parsing options
    # Later when we get the config, we will call this again with the config.
    configure_logging()

    if argv is None:
        argv = sys.argv

    argv = [str(x) for x in argv]
    config = parseoptions(argv, hook=hook)
    args = config.args

    # meta commmands
    if args.version:
        print(server_version)
        return

    if args.genconfig:
        from devpi_server.genconfig import genconfig
        return genconfig(config)

    configure_logging(config)
    xom = XOM(config)
    if not xom.is_replica():
        with xom.keyfs.transaction(write=True):
            set_default_indexes(xom.model)
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
        from devpi_server.model import run_passwd
        with xom.keyfs.transaction(write=True):
            return run_passwd(xom.model, config.args.passwd)

    return xom.main()


def make_application():
    """ entry point for making an application object with defaults. """
    config = parseoptions([])
    return XOM(config).create_app()

def wsgi_run(xom, app):
    from waitress import serve
    host = xom.config.args.host
    port = xom.config.args.port
    log = xom.log
    log.info("devpi-server version: %s", server_version)
    log.info("serverdir: %s" % xom.config.serverdir)
    log.info("uuid: %s" % xom.config.nodeinfo["uuid"])
    hostaddr = "http://%s:%s" % (host, port)
    log.info("serving at url: %s", hostaddr)
    log.info("bug tracker: https://bitbucket.org/hpk42/devpi/issues")
    log.info("IRC: #devpi on irc.freenode.net")
    if "WEBTRACE" in os.environ and xom.config.args.debug:
        from weberror.evalexception import make_eval_exception
        app = make_eval_exception(app, {})
    try:
        log.info("Hit Ctrl-C to quit.")
        serve(app, host=host, port=port, threads=50)
    except KeyboardInterrupt:
        pass
    return 0

class XOM:
    class Exiting(SystemExit):
        pass

    def __init__(self, config, proxy=None, httpget=None):
        self.config = config
        if proxy is not None:
            self.proxy = proxy
        self.thread_pool = mythread.ThreadPool()
        if httpget is not None:
            self.httpget = httpget
        sdir = config.serverdir
        if not (sdir.exists() and len(sdir.listdir()) >= 2):
            self.set_state_version(server_version)
        self.log = threadlog
        self.polling_replicas = {}

    def get_state_version(self):
        versionfile = self.config.serverdir.join(".serverversion")
        if not versionfile.exists():
            fatal("serverdir %s is unversioned, you may try use "
              "depvi-server-1.1 with the --upgrade-state option to "
              "upgrade from versions prior to 1.1\n" % self.config.serverdir)
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
        # need to initialize the pypi mirror state before importing
        # because importing may need pypi mirroring state
        if xom.is_replica():
            proxy = replica.PyPIProxy(xom._httpsession, xom.config.master_url)
        else:
            proxy = self.proxy
        xom.pypimirror.init_pypi_mirror(proxy)
        if args.export:
            from devpi_server.importexport import do_export
            #xom.thread_pool.start_one(xom.keyfs.notifier)
            return do_export(args.export, xom)

        if args.import_:
            from devpi_server.importexport import do_import
            # we need to start the keyfs notifier so that import
            # can wait on completion of events
            if args.wait_for_events:
                xom.thread_pool.start_one(xom.keyfs.notifier)
            return do_import(args.import_, xom)

        # creation of app will register handlers of key change events
        # which cannot happen anymore after the tx notifier has started
        with xom.keyfs.transaction():
            results = xom.config.hook.devpiserver_run_commands(xom=xom)
            if [x for x in results if x is not None]:
                errors = list(filter(None, results))
                if errors:
                    return errors[0]
                return 0

        app = xom.create_app()
        with xom.thread_pool.live():
            if xom.is_replica():
                # XXX ground restart_as_write_transaction better
                xom.keyfs.restart_as_write_transaction = None
            return wsgi_run(xom, app)

    def fatal(self, msg):
        self.thread_pool.shutdown()
        fatal(msg)

    @cached_property
    def filestore(self):
        from devpi_server.filestore import FileStore
        return FileStore(self)

    @cached_property
    def keyfs(self):
        from devpi_server.keyfs import KeyFS
        from devpi_server.model import add_keys
        keyfs = KeyFS(self.config.serverdir, readonly=self.is_replica())
        add_keys(self, keyfs)
        self.thread_pool.register(keyfs.notifier)
        return keyfs

    @cached_property
    def pypimirror(self):
        from devpi_server.extpypi import PyPIMirror
        return PyPIMirror(self)

    @cached_property
    def proxy(self):
        return extpypi.XMLProxy(PYPIURL_XMLRPC)

    def new_http_session(self, component_name):
        session = new_requests_session(agent=(component_name, server_version))
        session.cert = self.config.args.replica_cert
        return session

    @cached_property
    def _httpsession(self):
        return self.new_http_session("server")

    def httpget(self, url, allow_redirects, timeout=30, extra_headers=None):
        headers = {}
        if extra_headers:
            headers.update(extra_headers)
        USE_FRONT = self.config.args.bypass_cdn
        if USE_FRONT:
            self.log.debug("bypassing pypi CDN for: %s", url)
            if url.startswith("https://pypi.python.org/simple/"):
                url = url.replace("https://pypi", "https://front")
                headers["HOST"] = "pypi.python.org"
        try:
            resp = self._httpsession.get(
                        url, stream=True,
                        allow_redirects=allow_redirects,
                        headers=headers,
                        timeout=timeout)
            if USE_FRONT and resp.url.startswith("https://front.python.org"):
                resp.url = resp.url.replace("https://front.python.org",
                                            "https://pypi.python.org")
            return resp
        except self._httpsession.Errors:
            return FatalResponse(sys.exc_info())

    def create_app(self):
        from devpi_server.view_auth import DevpiAuthenticationPolicy
        from devpi_server.views import OutsideURLMiddleware
        from devpi_server.views import route_url
        from pkg_resources import get_distribution
        from pyramid.authorization import ACLAuthorizationPolicy
        from pyramid.config import Configurator
        log = self.log
        log.debug("creating application in process %s", os.getpid())
        pyramid_config = Configurator(root_factory='devpi_server.view_auth.RootFactory')
        pyramid_config.set_authentication_policy(DevpiAuthenticationPolicy(self))
        pyramid_config.set_authorization_policy(ACLAuthorizationPolicy())

        version_info = [
            ("devpi-server", get_distribution("devpi_server").version)]
        for plug, distinfo in self.config.hook._plugins:
            if distinfo is None:
                continue
            threadlog.info("Found plugin %s-%s (%s)." % (
                distinfo.project_name, distinfo.version, distinfo.location))
            version_info.append((distinfo.project_name, distinfo.version))
        version_info.sort()
        pyramid_config.registry['devpi_version_info'] = version_info
        self.config.hook.devpiserver_pyramid_configure(
                config=self.config,
                pyramid_config=pyramid_config)

        pyramid_config.add_route("/+changelog/{serial}",
                                 "/+changelog/{serial}")
        pyramid_config.add_route("/+status", "/+status")
        pyramid_config.add_route("/root/pypi/+name2serials",
                                 "/root/pypi/+name2serials")
        pyramid_config.add_route("/+api", "/+api", accept="application/json")
        pyramid_config.add_route("{path:.*}/+api", "{path:.*}/+api", accept="application/json")
        pyramid_config.add_route("/+login", "/+login", accept="application/json")
        pyramid_config.add_route("/{user}/{index}/+e/{relpath:.*}", "/{user}/{index}/+e/{relpath:.*}")
        pyramid_config.add_route("/{user}/{index}/+f/{relpath:.*}", "/{user}/{index}/+f/{relpath:.*}")
        pyramid_config.add_route("/{user}/{index}/+simple/", "/{user}/{index}/+simple/")
        pyramid_config.add_route("/{user}/{index}/+simple/{name}", "/{user}/{index}/+simple/{name:[^/]+/?}")
        pyramid_config.add_route("/{user}/{index}/+simple/{name}/refresh", "/{user}/{index}/+simple/{name}/refresh")
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

        # register tweens for logging, transaction and replication
        pyramid_config.add_tween("devpi_server.views.tween_request_logging")
        if self.is_replica():
            pyramid_config.add_tween(
                "devpi_server.replica.tween_replica_proxy",
                over="devpi_server.views.tween_keyfs_transaction",
                under="devpi_server.views.tween_request_logging",
            )
        pyramid_config.add_tween("devpi_server.views.tween_keyfs_transaction",
            under="devpi_server.views.tween_request_logging"
        )
        pyramid_config.add_request_method(get_remote_ip)
        pyramid_config.add_request_method(stage_url)
        pyramid_config.add_request_method(simpleindex_url)

        # overwrite route_url method with our own
        pyramid_config.add_request_method(route_url)
        # XXX end hack
        pyramid_config.scan()
        pyramid_config.registry['xom'] = self
        app = pyramid_config.make_wsgi_app()
        if self.is_replica():
            from devpi_server.replica import ReplicaThread
            replica_thread = ReplicaThread(self)
            # the replica thread replays keyfs changes
            # and pypimirror.name2serials changes are discovered
            # and replayed through the PypiProjectChange event
            self.thread_pool.register(replica_thread)
        else:
            # the master thread directly syncs using the
            # pypi changelog protocol
            self.thread_pool.register(self.pypimirror,
                                      dict(proxy=self.proxy))
        return OutsideURLMiddleware(app, self)

    def is_replica(self):
        return bool(self.config.args.master_url)

class FatalResponse:
    status_code = -1

    def __init__(self, excinfo=None):
        self.excinfo = excinfo

def get_remote_ip(request):
    return request.headers.get("X-REAL-IP", request.client_addr)


def stage_from_args(model, *args):
    if len(args) not in (1, 2):
        raise TypeError("stage_url() takes 1 or 2 arguments (%s given)" % len(args))
    if len(args) == 1:
        if isinstance(args[0], BaseStage):
            return args[0]
    return model.getstage(*args)


def stage_url(request, *args):
    model = request.registry['xom'].model
    stage = stage_from_args(model, *args)
    if stage is not None:
        return request.route_url(
            "/{user}/{index}", user=stage.username, index=stage.index)


def simpleindex_url(request, *args):
    model = request.registry['xom'].model
    stage = stage_from_args(model, *args)
    if stage is not None:
        return request.route_url(
            "/{user}/{index}/+simple/", user=stage.username, index=stage.index)


def set_default_indexes(model):
    root_user = model.get_user("root")
    if not root_user:
        root_user = model.create_user("root", "")
        threadlog.info("created root user")
    userconfig = root_user.key.get()
    indexes = userconfig["indexes"]
    if "pypi" not in indexes:
        indexes["pypi"] = {"bases": (), "type": "mirror", "volatile": False}
        root_user.key.set(userconfig)
        threadlog.info("created root/pypi index")
