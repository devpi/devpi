# PYTHON_ARGCOMPLETE_OK
"""
a WSGI server to serve PyPI compatible indexes and a full
recursive cache of pypi.org packages.
"""
import aiohttp
import inspect
import os
import os.path
import asyncio
import py
import ssl
import sys
import threading
import time

from requests import Response, exceptions
from requests.utils import DEFAULT_CA_BUNDLE_PATH
from devpi_common.types import cached_property
from devpi_common.request import new_requests_session
from .config import parseoptions, get_pluginmanager
from .exceptions import lazy_format_exception_only
from .log import configure_logging, threadlog
from .log import thread_push_log
from .model import BaseStage
from .model import RootModel
from .views import apireturn
from . import mythread
from . import __version__ as server_version


class Fatal(Exception):
    pass


def fatal(msg):
    raise Fatal(msg)


DATABASE_VERSION = "4"


def check_compatible_version(config):
    if not config.serverdir.exists():
        return
    state_version = get_state_version(config)
    if server_version != state_version:
        state_ver = tuple(state_version.split("."))
        if state_ver[0] != DATABASE_VERSION:
            fatal("Incompatible state: server %s cannot run serverdir "
                  "%s created at database version %s.\n"
                  "Use devpi-export from older version, then "
                  "devpi-import with newer version."
                  % (server_version, config.serverdir, state_ver[0]))


def get_state_version(config):
    versionfile = config.serverdir.join(".serverversion")
    if not versionfile.exists():
        fatal(
            "serverdir %s is non-empty and misses devpi-server meta information. "
            "You need to specify an empty directory or a directory that was "
            "previously managed by devpi-server>=1.2" % config.serverdir)
    return versionfile.read()


def set_state_version(config, version=DATABASE_VERSION):
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
        tw.line("fatal: %s" % e.args[0], red=True)
        return 1


def xom_from_config(config, init=False):
    check_compatible_version(config)

    # read/create node UUID and role of this server
    config.init_nodeinfo()

    if not init and config.sqlite_file_needed_but_missing():
        fatal(
            "No sqlite storage found in %s."
            " Or you need to run with --storage to specify the storage type,"
            " or you first need to run devpi-init or devpi-import"
            " in order to create the sqlite database." % config.serverdir
        )

    return XOM(config)


def init_default_indexes(xom):
    # we deliberately call get_current_serial first to establish a connection
    # to the backend and in case of sqlite create the database
    if xom.keyfs.get_current_serial() == -1 and not xom.is_replica():
        with xom.keyfs.transaction(write=True):
            set_default_indexes(xom.model)


def _main(pluginmanager, argv=None):
    # During parsing of options logging should not be used

    if argv is None:
        argv = sys.argv

    argv = [str(x) for x in argv]
    config = parseoptions(pluginmanager, argv)
    args = config.args

    # meta commands
    if args.version:
        print(server_version)
        return 0

    # now we can configure logging
    configure_logging(config.args)

    if not config.path_nodeinfo.exists():
        fatal("The path '%s' contains no devpi-server data, use devpi-init to initialize." % config.serverdir)

    xom = xom_from_config(config)

    return xom.main()


def make_application():
    """ entry point for making an application object with defaults. """
    config = parseoptions(get_pluginmanager(), [])
    return XOM(config).create_app()


def wsgi_run(xom, app):
    from waitress import serve
    log = xom.log
    kwargs = xom.config.waitress_info["kwargs"]
    addresses = xom.config.waitress_info["addresses"]
    log.info("devpi-server version: %s", server_version)
    log.info("serverdir: %s" % xom.config.serverdir)
    log.info("uuid: %s" % xom.config.nodeinfo["uuid"])
    if len(addresses) == 1:
        log.info("serving at url: %s", addresses[0])
    else:
        log.info("serving at urls: %s", ", ".join(addresses))
    log.info("using %s threads", kwargs['threads'])
    log.info("bug tracker: https://github.com/devpi/devpi/issues")
    if "WEBTRACE" in os.environ and xom.config.args.debug:
        from weberror.evalexception import make_eval_exception
        app = make_eval_exception(app, {})
    try:
        log.info("Hit Ctrl-C to quit.")
        serve(app, **kwargs)
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


class AsyncioLoopThread(object):

    def __init__(self, xom):
        self.xom = xom
        self._started = mythread.threading.Event()

    @property
    def loop(self):
        if self._started.wait(2):
            return self._loop
        fatal("Couldn't get async loop, was the thread not started?")

    def thread_run(self):
        thread_push_log("[ASYN]")
        threadlog.info("Starting asyncio event loop")
        self._loop = asyncio.new_event_loop()
        self._started.set()
        while 1:
            try:
                self.loop.run_forever()
            except Exception:
                threadlog.exception("Exception in asyncio event loop")
            finally:
                threadlog.info("The asyncio event loop stopped")
            return

    def thread_shutdown(self):
        loop = self.loop
        try:
            loop.call_soon_threadsafe(loop.stop)
        except RuntimeError:
            # the shutdown function may have been called already
            return
        while loop.is_running():
            time.sleep(0.1)
        loop.close()


class XOM:
    class Exiting(SystemExit):
        pass

    def __init__(self, config, httpget=None):
        self.config = config
        self.thread_pool = mythread.ThreadPool()
        self.async_thread = AsyncioLoopThread(self)
        self.async_tasks = set()
        self.thread_pool.register(self.async_thread)
        if httpget is not None:
            self.httpget = httpget
            self.async_httpget = httpget.async_httpget
        self.log = threadlog
        self.polling_replicas = {}
        self._stagecache = {}
        self._stagecache_lock = threading.Lock()
        if self.is_replica():
            from devpi_server.replica import ReplicaThread
            from devpi_server.replica import register_key_subscribers
            search_path = self.config.replica_file_search_path
            if search_path and not os.path.exists(search_path):
                fatal(
                    "search path for existing replica files doesn't "
                    "exist: %s" % search_path)
            register_key_subscribers(self)
            # the replica thread replays keyfs changes
            # and project-specific changes are discovered
            # and replayed through the PypiProjectChange event
            if not self.config.requests_only:
                self.replica_thread = ReplicaThread(self)
                self.thread_pool.register(self.replica_thread)

    def create_future(self):
        return self.async_thread.loop.create_future()

    async def _with_timeout(self, coroutine, timeout):
        return await asyncio.wait_for(asyncio.shield(coroutine), timeout)

    def _run_coroutine_threadsafe(self, coroutine, timeout=None):
        if timeout is not None:
            coroutine = self._with_timeout(coroutine, timeout)
        return asyncio.run_coroutine_threadsafe(
            coroutine,
            loop=self.async_thread.loop)

    def run_coroutine_threadsafe(self, coroutine, timeout=None):
        future = self._run_coroutine_threadsafe(coroutine, timeout=timeout)
        exc = future.exception()
        if exc:
            raise exc
        return future.result()

    def create_task(self, coroutine):
        task = asyncio.ensure_future(coroutine, loop=self.async_thread.loop)
        # keep a strong reference
        self.async_tasks.add(task)
        # automatically remove the reference when done
        task.add_done_callback(self.async_tasks.discard)

    def get_singleton(self, indexpath, key):
        """ return a per-xom singleton for the given indexpath and key
        or raise KeyError if no such singleton was set yet.
        """
        with self._stagecache_lock:
            return self._stagecache[indexpath][key]

    def set_singleton(self, indexpath, key, obj):
        """ set the singleton for indexpath/key to obj. """
        with self._stagecache_lock:
            s = self._stagecache.setdefault(indexpath, {})
            s[key] = obj

    def setdefault_singleton(self, indexpath, key, *, default=None, factory=None):
        """ get existing singleton, or set the default for indexpath/key to obj. """
        assert default is None or factory is None
        with self._stagecache_lock:
            s = self._stagecache.setdefault(indexpath, {})
            if key not in s:
                if default is None:
                    default = factory()
                s[key] = default
            return s[key]

    def del_singletons(self, indexpath):
        """ delete all singletones for the given indexpath """
        with self._stagecache_lock:
            self._stagecache.pop(indexpath, None)

    @cached_property
    def supported_features(self):
        results = set((
            'server-keyvalue-parsing',
        ))
        for features in self.config.hook.devpiserver_get_features():
            results.update(features)
        return tuple(sorted(results))

    @property
    def model(self):
        """ root model object. """
        try:
            tx = self.keyfs.tx
        except AttributeError:
            return RootModel(self)
        else:
            return tx.get_model(self)

    def main(self):
        xom = self

        # creation of app will register handlers of key change events
        # which cannot happen anymore after the tx notifier has started
        with xom.keyfs.transaction():
            res = xom.config.hook.devpiserver_cmdline_run(xom=xom)
            if res is not None:
                return res

        app = xom.create_app()
        if xom.is_replica():
            # XXX ground restart_as_write_transaction better
            xom.keyfs.restart_as_write_transaction = None
        return xom.thread_pool.run(wsgi_run, xom, app)

    def fatal(self, msg):
        self.keyfs.release_all_wait_tx()
        self.thread_pool.shutdown()
        fatal(msg)

    @cached_property
    def filestore(self):
        from devpi_server.filestore import FileStore
        return FileStore(self.keyfs)

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
        try:
            keyfs.finalize_init()
        except Exception:
            threadlog.exception("Error while trying to initialize storage")
            fatal("Couldn't initialize storage")
        if not self.config.requests_only:
            self.thread_pool.register(keyfs.notifier)
        return keyfs

    def new_http_session(self, component_name, max_retries=None):
        session = new_requests_session(agent=(component_name, server_version), max_retries=max_retries)
        session.cert = self.config.replica_cert
        return session

    @cached_property
    def _httpsession(self):
        max_retries = self.config.replica_max_retries
        return self.new_http_session("server", max_retries=max_retries)

    @cached_property
    def _ssl_context(self):
        # create an SSLContext object that uses the same CA certs as requests
        cafile = (
            os.environ.get("REQUESTS_CA_BUNDLE")
            or os.environ.get("CURL_CA_BUNDLE")
            or DEFAULT_CA_BUNDLE_PATH
        )
        if cafile and not os.path.exists(cafile):
            threadlog.warning(
                "Could not find a suitable TLS CA certificate bundle, invalid path: %s",
                cafile
            )
            cafile = None

        return ssl.create_default_context(cafile=cafile)

    def _close_sessions(self):
        self._httpsession.close()

    async def async_httpget(self, url, allow_redirects, timeout=None, extra_headers=None):
        timeout = aiohttp.ClientTimeout(total=timeout)
        connector = aiohttp.TCPConnector(ssl=self._ssl_context)
        try:
            async with aiohttp.ClientSession(timeout=timeout, connector=connector, trust_env=True) as session:
                async with session.get(
                    url, allow_redirects=allow_redirects, headers=extra_headers
                ) as response:
                    if response.status < 300:
                        text = await response.text()
                    else:
                        text = None
                    return (response, text)
        except OSError as e:
            location = get_caller_location()
            threadlog.warn(
                "OS error during async_httpget of %s at %s: %s",
                url, location, lazy_format_exception_only(e))
            return FatalResponse(url, repr(sys.exc_info()[1]))
        except aiohttp.ClientError as e:
            location = get_caller_location()
            threadlog.warn(
                "OS error during async_httpget of %s at %s: %s",
                url, location, lazy_format_exception_only(e))
            return FatalResponse(url, repr(sys.exc_info()[1]))

    def httpget(self, url, allow_redirects, timeout=None, extra_headers=None):
        if self.config.offline_mode:
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
        except OSError as e:
            location = get_caller_location()
            threadlog.warn(
                "OS error during httpget of %s at %s: %s",
                url, location, lazy_format_exception_only(e))
            return FatalResponse(url, repr(sys.exc_info()[1]))
        except exceptions.ConnectionError as e:
            location = get_caller_location()
            threadlog.warn(
                "Connection error during httpget of %s at %s: %s",
                url, location, lazy_format_exception_only(e))
            return FatalResponse(url, repr(sys.exc_info()[1]))
        except self._httpsession.Errors as e:
            location = get_caller_location()
            threadlog.warn(
                "HTTPError during httpget of %s at %s: %s",
                url, location, lazy_format_exception_only(e))
            return FatalResponse(url, repr(sys.exc_info()[1]))
        else:
            return resp

    def view_deriver(self, view, info):
        if self.is_replica():
            if info.options.get('is_mutating', True):
                from .model import ensure_list
                from .replica import proxy_view_to_master
                from .views import is_mutating_http_method
                request_methods = info.options['request_method']
                if request_methods is None:
                    request_methods = []
                for request_method in ensure_list(request_methods):
                    if is_mutating_http_method(request_method):
                        # we got a view which uses a mutating method and isn't
                        # marked to be excluded, so we replace the view with
                        # one that proxies to the master, because a replica
                        # must not modify its database except via the
                        # replication protocol
                        return proxy_view_to_master
        return view
    view_deriver.options = ('is_mutating',)  # type: ignore

    def create_app(self):
        from devpi_server.middleware import OutsideURLMiddleware
        from devpi_server.view_auth import DevpiSecurityPolicy
        from devpi_server.views import ContentTypePredicate
        from devpi_server.views import route_url, INSTALLER_USER_AGENT
        from pyramid.config import Configurator
        from pyramid.viewderivers import INGRESS
        log = self.log
        log.info("running with role %r", self.config.role)
        log.debug("creating application in process %s", os.getpid())
        pyramid_config = Configurator(root_factory='devpi_server.view_auth.RootFactory')
        pyramid_config.set_security_policy(DevpiSecurityPolicy(self))

        version_info = [("devpi-server", server_version)]
        for plug, distinfo in self.config.pluginmanager.list_plugin_distinfo():
            key = (distinfo.project_name, distinfo.version)
            if key not in version_info:
                threadlog.info("Found plugin %s-%s." % key)
                version_info.append(key)
        version_info.sort()
        pyramid_config.registry['devpi_version_info'] = version_info
        pyramid_config.registry['xom'] = self
        index_classes = {}
        customizer_classes = sum(
            self.config.hook.devpiserver_get_stage_customizer_classes(),
            [])
        for ixtype, ixclass in customizer_classes:
            index_classes.setdefault(ixtype, []).append(ixclass)
        for ixtype, ixclasses in index_classes.items():
            if len(ixclasses) > 1:
                fatal(
                    "multiple implementation classes for index type '%s':\n%s"
                    % (
                        ixtype,
                        "\n".join(
                            "%s.%s" % (x.__module__, x.__name__)
                            for x in ixclasses)))
        self.config.hook.devpiserver_pyramid_configure(
            config=self.config,
            pyramid_config=pyramid_config)

        pyramid_config.add_view_deriver(self.view_deriver, under=INGRESS)
        pyramid_config.add_view_predicate('content_type', ContentTypePredicate)

        pyramid_config.add_route("/+status", "/+status")
        pyramid_config.add_route("/+api", "/+api", accept="application/json")
        pyramid_config.add_route(
            "/{user}/+api",
            "/{user:[^+/]+}/+api",
            accept="application/json")
        pyramid_config.add_route(
            "/{user}/{index}/+api",
            "/{user:[^+/]+}/{index:[^+/]+}/+api",
            accept="application/json")
        pyramid_config.add_route("/+authcheck", "/+authcheck")
        pyramid_config.add_route("/+login", "/+login", accept="application/json")
        pyramid_config.add_route(
            "/{user}/{index}/+e/{relpath:.*}",
            "/{user:[^+/]+}/{index:[^+/]+}/+e/{relpath:.*}")
        pyramid_config.add_route(
            "/{user}/{index}/+f/{relpath:.*}",
            "/{user:[^+/]+}/{index:[^+/]+}/+f/{relpath:.*}")
        pyramid_config.add_route(
            "/{user}/{index}/+simple",
            "/{user:[^+/]+}/{index:[^+/]+}/+simple")
        pyramid_config.add_route(
            "/{user}/{index}/+simple/",
            "/{user:[^+/]+}/{index:[^+/]+}/+simple/")
        pyramid_config.add_route(
            "/{user}/{index}/+simple/{project}",
            "/{user:[^+/]+}/{index:[^+/]+}/+simple/{project:[^+/]+}")
        pyramid_config.add_route(
            "/{user}/{index}/+simple/{project}/",
            "/{user:[^+/]+}/{index:[^+/]+}/+simple/{project:[^+/]+}/")
        pyramid_config.add_route(
            "/{user}/{index}/+simple/{project}/refresh",
            "/{user:[^+/]+}/{index:[^+/]+}/+simple/{project:[^+/]+}/refresh")
        pyramid_config.add_route(
            "/{user}/{index}/{project}/{version}",
            "/{user:[^+/]+}/{index:[^+/]+}/{project:[^+/]+}/{version:[^/]+/?}")
        pyramid_config.add_route(
            "installer_simple",
            "/{user:[^+/]+}/{index:[^+/]+/?}",
            header="User-Agent:" + INSTALLER_USER_AGENT,
            request_method="GET")
        pyramid_config.add_route(
            "installer_simple_project", "/{user:[^+/]+}/{index}/{project:[^+/]+/?}",
            header="User-Agent:" + INSTALLER_USER_AGENT,
            request_method="GET")
        pyramid_config.add_route(
            "/{user}/{index}/{project}",
            "/{user:[^+/]+}/{index:[^+/]+}/{project:[^+/]+/?}")
        pyramid_config.add_route(
            "/{user}/{index}/",
            "/{user:[^+/]+}/{index:[^+/]+}/")
        pyramid_config.add_route(
            "/{user}/{index}",
            "/{user:[^+/]+}/{index:[^+/]+}")
        pyramid_config.add_route(
            "/{user}/",
            "/{user:[^+/]+}/")
        pyramid_config.add_route(
            "/{user}",
            "/{user:[^+/]+}")
        pyramid_config.add_route("/", "/")

        pyramid_config.add_accept_view_order(
            'application/vnd.pypi.simple.v1+json')
        pyramid_config.add_accept_view_order(
            'application/json',
            weighs_more_than='application/vnd.pypi.simple.v1+json')
        pyramid_config.add_accept_view_order(
            'text/html',
            weighs_more_than='application/json')

        # register tweens for logging, transaction and replication
        pyramid_config.add_tween("devpi_server.views.tween_request_logging")
        pyramid_config.add_tween(
            "devpi_server.views.tween_keyfs_transaction",
            under="devpi_server.views.tween_request_logging")
        if self.config.args.profile_requests:
            pyramid_config.add_tween("devpi_server.main.tween_request_profiling")
        pyramid_config.add_request_method(get_remote_ip)
        pyramid_config.add_request_method(stage_url)
        pyramid_config.add_request_method(simpleindex_url)
        pyramid_config.add_request_method(apifatal)
        pyramid_config.add_request_method(apireturn_for_request, "apireturn")

        # overwrite route_url method with our own
        pyramid_config.add_request_method(route_url)
        # XXX end hack
        pyramid_config.scan("devpi_server.views")
        app = pyramid_config.make_wsgi_app()
        return OutsideURLMiddleware(app, self)

    def is_master(self):
        return self.config.role == "master"

    def is_replica(self):
        return self.config.role == "replica"


class FatalResponse:
    status_code = -1

    def __init__(self, url, reason):
        self.url = url
        self.reason = reason
        self.status = self.status_code

    def __repr__(self):
        return "%s(%r)" % (self.__class__.__name__, self.reason)

    # an adapter to allow this to be used in async_httpget
    def __iter__(self):
        yield self
        yield self.reason

    def close(self):
        pass


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


def apireturn_for_request(request, *args, **kwargs):
    apireturn(*args, **kwargs)


def set_default_indexes(model):
    root_user = model.get_user("root")
    if not root_user:
        root_user = model.create_user(
            "root",
            model.xom.config.root_passwd,
            pwhash=model.xom.config.root_passwd_hash)
        threadlog.info("created root user")
    userconfig = root_user.key.get(readonly=False)
    indexes = userconfig["indexes"]
    if "pypi" not in indexes and not model.xom.config.no_root_pypi:
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
