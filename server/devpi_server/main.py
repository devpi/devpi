# PYTHON_ARGCOMPLETE_OK
"""
a WSGI server to serve PyPI compatible indexes and a full
recursive cache of pypi.org packages.
"""
from __future__ import unicode_literals
import inspect
import os, sys
import py

from requests import Response, exceptions
from devpi_common.types import cached_property
from devpi_common.request import new_requests_session
from .config import parseoptions, get_pluginmanager
from .log import configure_logging, threadlog
from .model import BaseStage
from .views import apireturn
from . import mythread
from . import __version__ as server_version


class Fatal(Exception):
    pass

def fatal(msg):
    raise Fatal(msg)


DATABASE_VERSION = "4"


def check_compatible_version(config):
    args = config.args
    if args.export:
        return
    state_version = get_state_version(config)
    if server_version != state_version:
        state_ver = tuple(state_version.split("."))
        if state_ver[0] != DATABASE_VERSION:
            fatal("Incompatible state: server %s cannot run serverdir "
                  "%s created at database version %s.\n"
                  "Use --export from older version, then --import with newer "
                  "version."
                  % (server_version, config.serverdir, state_ver[0]))


def get_state_version(config):
    versionfile = config.serverdir.join(".serverversion")
    if not versionfile.exists():
        fatal(
            "serverdir %s is non-empty and misses devpi-server meta information. "
            "You need to specify an empty directory or a directory that was "
            "previously managed by devpi-server>=1.2" % config.serverdir)
    return versionfile.read()


def set_state_version(config, version):
    versionfile = config.serverdir.join(".serverversion")
    versionfile.dirpath().ensure(dir=1)
    versionfile.write(version)


def main(argv=None):
    """ devpi-server command line entry point. """
    pluginmanager = get_pluginmanager()
    try:
        return _main(pluginmanager, argv=argv)
    except Fatal as e:
        tw = py.io.TerminalWriter(sys.stderr)
        tw.line("fatal: %s" %  e.args[0], red=True)
        return 1

def _main(pluginmanager, argv=None):
    # During parsing of options logging should not be used

    if argv is None:
        argv = sys.argv

    argv = [str(x) for x in argv]
    config = parseoptions(pluginmanager, argv)
    args = config.args

    # meta commmands
    if args.version:
        print(server_version)
        return 0

    if args.genconfig:
        from devpi_server.genconfig import genconfig
        return genconfig(config, argv[1:])

    configure_logging(config.args)

    if args.init:
        if config.path_nodeinfo.exists():
            fatal("The path '%s' already contains devpi-server data." % config.serverdir)
    elif not args.import_:
        if not config.path_nodeinfo.exists():
            fatal("The path '%s' contains no devpi-server data, use --init to initialize." % config.serverdir)

    if args.init or args.import_:
        sdir = config.serverdir
        if not (sdir.exists() and len(sdir.listdir()) >= 2):
            set_state_version(config, DATABASE_VERSION)
    else:
        check_compatible_version(config)

    # read/create node UUID and role of this server
    config.init_nodeinfo()

    xom = XOM(config)
    if not xom.is_replica() and xom.keyfs.get_current_serial() == -1:
        with xom.keyfs.transaction(write=True):
            set_default_indexes(xom.model)

    if args.start or args.stop or args.log or args.status:
        xprocdir = config.serverdir.join(".xproc")
        from devpi_server.bgserver import BackgroundServer
        tw = py.io.TerminalWriter()
        bgserver = BackgroundServer(tw, xprocdir)
        if args.start:
            return bgserver.start(args, argv[1:])
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

    if args.init:
        return 0

    return xom.main()


def make_application():
    """ entry point for making an application object with defaults. """
    config = parseoptions(get_pluginmanager(), [])
    return XOM(config).create_app()

def wsgi_run(xom, app):
    from waitress import serve
    host = xom.config.args.host
    port = xom.config.args.port
    threads = xom.config.args.threads
    max_body = xom.config.args.max_request_body_size
    log = xom.log
    log.info("devpi-server version: %s", server_version)
    log.info("serverdir: %s" % xom.config.serverdir)
    log.info("uuid: %s" % xom.config.nodeinfo["uuid"])
    hostaddr = "http://%s:%s" % (host, port)
    hostaddr6 = "http://[%s]:%s" % (host, port)
    log.info("serving at url: %s (might be %s for IPv6)", hostaddr, hostaddr6)
    log.info("using %s threads", threads)
    log.info("bug tracker: https://github.com/devpi/devpi/issues")
    log.info("IRC: #devpi on irc.freenode.net")
    if "WEBTRACE" in os.environ and xom.config.args.debug:
        from weberror.evalexception import make_eval_exception
        app = make_eval_exception(app, {})
    try:
        log.info("Hit Ctrl-C to quit.")
        serve(app, host=host, port=port, threads=threads, max_request_body_size=max_body)
    except KeyboardInterrupt:
        pass
    return 0


def get_caller_location():
    frame = inspect.currentframe()
    if frame is None:
        return 'unknown (no current frame)'
    caller_frame = frame.f_back.f_back
    return "%s:%s::%s" % (
        caller_frame.f_code.co_filename,
        caller_frame.f_lineno,
        caller_frame.f_code.co_name)


class XOM:
    class Exiting(SystemExit):
        pass

    def __init__(self, config, httpget=None):
        self.config = config
        self.thread_pool = mythread.ThreadPool()
        if httpget is not None:
            self.httpget = httpget
        self.log = threadlog
        self.polling_replicas = {}
        self._stagecache = {}

    def get_singleton(self, indexpath, key):
        """ return a per-xom singleton for the given indexpath and key
        or raise KeyError if no such singleton was set yet.
        """
        return self._stagecache[indexpath][key]

    def set_singleton(self, indexpath, key, obj):
        """ set the singleton for indexpath/key to obj. """
        s = self._stagecache.setdefault(indexpath, {})
        s[key] = obj

    def del_singletons(self, indexpath):
        """ delete all singletones for the given indexpath """
        self._stagecache.pop(indexpath, None)

    @cached_property
    def supported_features(self):
        results = set((
            'server-keyvalue-parsing',
        ))
        for features in self.config.hook.devpiserver_get_features():
            results.update(features)
        return tuple(sorted(results))

    @cached_property
    def model(self):
        """ root model object. """
        from devpi_server.model import RootModel
        return RootModel(self)

    def main(self):
        xom = self
        args = xom.config.args
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
            res = xom.config.hook.devpiserver_cmdline_run(xom=xom)
            if res is not None:
                return res

        app = xom.create_app()
        with xom.thread_pool.live():
            if xom.is_replica():
                # XXX ground restart_as_write_transaction better
                xom.keyfs.restart_as_write_transaction = None
            return wsgi_run(xom, app)

    def fatal(self, msg):
        self.keyfs.release_all_wait_tx()
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
        keyfs = KeyFS(
            self.config.serverdir,
            self.config.storage,
            readonly=self.is_replica(),
            cache_size=self.config.args.keyfs_cache_size)
        add_keys(self, keyfs)
        if not self.config.args.requests_only:
            self.thread_pool.register(keyfs.notifier)
        return keyfs

    def new_http_session(self, component_name, max_retries=None):
        session = new_requests_session(agent=(component_name, server_version), max_retries=max_retries)
        session.cert = self.config.args.replica_cert
        return session

    @cached_property
    def _httpsession(self):
        return self.new_http_session("server", max_retries=self.config.args.replica_max_retries)

    def httpget(self, url, allow_redirects, timeout=None, extra_headers=None):
        if self.config.args.offline_mode:
            resp = Response()
            resp.status_code = 503  # service unavailable
            return resp
        headers = {}
        if extra_headers:
            headers.update(extra_headers)
        try:
            resp = self._httpsession.get(
                        url, stream=True,
                        allow_redirects=allow_redirects,
                        headers=headers,
                        timeout=timeout or self.config.args.request_timeout)
            return resp
        except OSError:
            location = get_caller_location()
            threadlog.warn("OS error during httpget of %s at %s", url, location)
            return FatalResponse(repr(sys.exc_info()[1]))
        except exceptions.ConnectionError:
            location = get_caller_location()
            threadlog.warn("Connection error during httpget of %s at %s", url, location)
            return FatalResponse(repr(sys.exc_info()[1]))
        except self._httpsession.Errors:
            location = get_caller_location()
            threadlog.warn("HTTPError during httpget of %s at %s", url, location)
            return FatalResponse(repr(sys.exc_info()[1]))

    def create_app(self):
        from devpi_server.view_auth import DevpiAuthenticationPolicy
        from devpi_server.views import ContentTypePredicate
        from devpi_server.views import OutsideURLMiddleware
        from devpi_server.views import route_url, INSTALLER_USER_AGENT
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
        for plug, distinfo in self.config.pluginmanager.list_plugin_distinfo():
            threadlog.info("Found plugin %s-%s (%s)." % (
                distinfo.project_name, distinfo.version, distinfo.location))
            key = (distinfo.project_name, distinfo.version)
            if key not in version_info:
                version_info.append(key)
        version_info.sort()
        pyramid_config.registry['devpi_version_info'] = version_info
        pyramid_config.registry['xom'] = self
        self.config.hook.devpiserver_pyramid_configure(
                config=self.config,
                pyramid_config=pyramid_config)

        pyramid_config.add_view_predicate('content_type', ContentTypePredicate)

        pyramid_config.add_route("/+changelog/{serial}",
                                 r"/+changelog/{serial:\d+}")
        pyramid_config.add_route("/+changelog/{serial}-",
                                 r"/+changelog/{serial:\d+}-")
        pyramid_config.add_route("/+status", "/+status")
        pyramid_config.add_route("/+api", "/+api", accept="application/json")
        pyramid_config.add_route("{path:.*}/+api", "{path:.*}/+api", accept="application/json")
        pyramid_config.add_route("/+login", "/+login", accept="application/json")
        pyramid_config.add_route("/{user}/{index}/+e/{relpath:.*}", "/{user}/{index}/+e/{relpath:.*}")
        pyramid_config.add_route("/{user}/{index}/+f/{relpath:.*}", "/{user}/{index}/+f/{relpath:.*}")
        pyramid_config.add_route("/{user}/{index}/+simple", "/{user}/{index}/+simple")
        pyramid_config.add_route("/{user}/{index}/+simple/", "/{user}/{index}/+simple/")
        pyramid_config.add_route("/{user}/{index}/+simple/{project}",
                                 "/{user}/{index}/+simple/{project}")
        pyramid_config.add_route("/{user}/{index}/+simple/{project}/",
                                 "/{user}/{index}/+simple/{project}/")
        pyramid_config.add_route("/{user}/{index}/+simple/{project}/refresh",
                                 "/{user}/{index}/+simple/{project}/refresh")
        pyramid_config.add_route("/{user}/{index}/{project}/{version}",
                                 "/{user}/{index}/{project}/{version:[^/]+/?}")
        pyramid_config.add_route(
            "simple_redirect", "/{user}/{index}/{project:[^/]+/?}",
            header="User-Agent:" + INSTALLER_USER_AGENT,
            accept="text/html",
        )
        pyramid_config.add_route("/{user}/{index}/{project}",
                                 "/{user}/{index}/{project:[^/]+/?}")
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
        if self.config.args.profile_requests:
            pyramid_config.add_tween("devpi_server.main.tween_request_profiling")
        pyramid_config.add_request_method(get_remote_ip)
        pyramid_config.add_request_method(stage_url)
        pyramid_config.add_request_method(simpleindex_url)
        pyramid_config.add_request_method(apifatal)

        # overwrite route_url method with our own
        pyramid_config.add_request_method(route_url)
        # XXX end hack
        pyramid_config.scan()
        app = pyramid_config.make_wsgi_app()
        if self.is_replica():
            from devpi_server.replica import ReplicaThread, register_key_subscribers
            search_path = self.config.args.replica_file_search_path
            if search_path and not os.path.exists(search_path):
                fatal(
                    "search path for existing replica files doesn't "
                    "exist: %s" % search_path)
            register_key_subscribers(self)
            self.replica_thread = ReplicaThread(self)
            # the replica thread replays keyfs changes
            # and project-specific changes are discovered
            # and replayed through the PypiProjectChange event
            if not self.config.args.requests_only:
                self.thread_pool.register(self.replica_thread)
        return OutsideURLMiddleware(app, self)

    def is_master(self):
        return self.config.role == "master"

    def is_replica(self):
        return self.config.role == "replica"


class FatalResponse:
    status_code = -1

    def __init__(self, reason):
        self.reason = reason

    def __repr__(self):
        return "%s(%r)" % (self.__class__.__name__, self.reason)


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


def apifatal(request, *args, **kwargs):
    request.registry["xom"].keyfs.tx.doom()
    apireturn(*args, **kwargs)


def set_default_indexes(model):
    root_user = model.get_user("root")
    if not root_user:
        root_user = model.create_user(
            "root",
            model.xom.config.args.root_passwd,
            pwhash=model.xom.config.args.root_passwd_hash)
        threadlog.info("created root user")
    userconfig = root_user.key.get(readonly=False)
    indexes = userconfig["indexes"]
    if "pypi" not in indexes and not model.xom.config.args.no_root_pypi:
        indexes["pypi"] = _pypi_ixconfig_default.copy()
        root_user.key.set(userconfig)
        threadlog.info("created root/pypi index")

_pypi_ixconfig_default = {
    "type": "mirror", "volatile": False,
    "title": "PyPI",
    "mirror_url": "https://pypi.org/simple/",
    "mirror_web_url_fmt": "https://pypi.org/project/{name}/"}


def tween_request_profiling(handler, registry):
    from cProfile import Profile
    req = [0]
    num_profile = registry["xom"].config.args.profile_requests
    # we need to use a list, so we can create a new Profile instance without
    # getting variable scope issues
    profile = [Profile()]

    def request_profiling_handler(request):
        profile[0].enable()
        try:
            return handler(request)
        finally:
            profile[0].disable()
            req[0] += 1
            if req[0] >= num_profile:
                profile[0].print_stats("cumulative")
                req[0] = 0
                profile[:] = [Profile()]
    return request_profiling_handler
