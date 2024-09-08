import argon2
import base64
import os.path
import argparse
import secrets
import sys
import uuid
from operator import itemgetter
from pathlib import Path
from tempfile import NamedTemporaryFile
from pluggy import HookimplMarker, PluginManager
import py
from devpi_common.types import cached_property
from functools import partial
from .log import threadlog
from . import fileutil
from . import hookspecs
import json
import devpi_server
from devpi_common.url import URL
import warnings


log = threadlog


hookimpl = HookimplMarker("devpiserver")


DEFAULT_MIRROR_CACHE_EXPIRY = 1800
DEFAULT_PROXY_TIMEOUT = 30
DEFAULT_REQUEST_TIMEOUT = 5
DEFAULT_FILE_REPLICATION_THREADS = 5
DEFAULT_ARGON2_MEMORY_COST = 524288
DEFAULT_ARGON2_PARALLELISM = 8
DEFAULT_ARGON2_TIME_COST = 16


def strtobool(val):
    val = val.lower()
    if val in ('y', 'yes', 't', 'true', 'on', '1'):
        return True
    elif val in ('n', 'no', 'f', 'false', 'off', '0'):
        return False
    else:
        raise ValueError(f"invalid truth value {val!r}")


def get_pluginmanager(load_entrypoints=True):
    pm = PluginManager("devpiserver")
    pm.add_hookspecs(hookspecs)
    # XXX load internal plugins here
    if load_entrypoints:
        pm.load_setuptools_entrypoints("devpi_server")
    pm.check_pending()
    return pm


def traced_pluggy_call(hook, **caller_kwargs):
    firstresult = hook.spec.opts.get("firstresult", False) if hook.spec else False
    results = []
    plugin_names = []
    hookimpls = hook._hookimpls if hasattr(hook, '_hookimpls') else hook.get_hookimpls()
    for hook_impl in reversed(hookimpls):
        args = [caller_kwargs[argname] for argname in hook_impl.argnames]
        res = hook_impl.function(*args)
        if res is not None:
            results.append(res)
            plugin_names.append(hook_impl.plugin_name)
            if firstresult:
                break
    if firstresult:
        results = results[0] if results else None
    return (results, plugin_names)


def add_help_option(parser, pluginmanager):
    parser.addoption(
        "-h", "--help",
        action='store_true', default='==SUPPRESS==',
        help="Show this help message and exit.")


def add_configfile_option(parser, pluginmanager):
    parser.addoption(
        "-c", "--configfile",
        type=str, default=None,
        help="Config file to use.")


def add_role_option(parser, pluginmanager):
    parser.addoption(
        "--role", action="store", dest="role", default="auto",
        choices=["master", "primary", "replica", "standalone", "auto"],
        help="set role of this instance. The default 'auto' sets "
             "'standalone' by default and 'replica' if the --primary-url "
             "option is used. To enable the replication protocol you have "
             "to explicitly set the 'primary' role. The 'master' role is "
             "the deprecated variant of 'primary'.")


def add_master_url_option(parser, pluginmanager):
    warnings.warn(
        "The add_master_url_option function is deprecated, "
        "use add_primary_url_option instead",
        DeprecationWarning,
        stacklevel=2)
    add_primary_url_option(parser, pluginmanager)


def add_primary_url_option(parser, pluginmanager):  # noqa: ARG001
    parser.addoption(
        "--primary-url", action="store", dest="primary_url",
        help="run as a replica of the specified primary server",
        default=None)
    parser.addoption(
        "--master-url", action="store", dest="deprecated_master_url",
        help="DEPRECATED, use --primary-url instead",
        default=None)


def add_hard_links_option(parser, pluginmanager):
    parser.addoption(
        "--hard-links", action="store_true",
        help="use hard links during export, import or with "
             " --replica-file-search-path instead of copying "
             "or downloading files. "
             "All limitations for hard links on your OS apply. "
             "USE AT YOUR OWN RISK")


def add_logging_options(parser, pluginmanager):
    parser.addoption(
        "--debug", action="store_true",
        help="run wsgi application with debug logging")

    parser.addoption(
        "--logger-cfg", action="store", dest="logger_cfg",
        help="path to .json or .yaml logger configuration file. ",
        default=None)


def add_web_options(parser, pluginmanager):
    parser.addoption(
        "--host", type=str,
        default="localhost",
        help="domain/ip address to listen on.  Use --host=0.0.0.0 if "
             "you want to accept connections from anywhere.")

    parser.addoption(
        "--port", type=int,
        default=3141,
        help="port to listen for http requests.")

    parser.addoption(
        "--listen", type=str, action="append",
        help="host:port combination to listen to for http requests. "
             "When using * for host bind to all interfaces. "
             "Use square brackets for ipv6 like [::1]:8080. "
             "You can specify more than one host:port combination "
             "with multiple --listen arguments.")

    parser.addoption(
        "--unix-socket", type=str,
        help="path to unix socket to bind to.")

    parser.addoption(
        "--unix-socket-perms", type=str,
        help="permissions for the unix socket if used, defaults to '600'.")

    parser.addoption(
        "--threads", type=int,
        default=50,
        help="number of threads to start for serving clients.")

    parser.addoption(
        "--connection-limit", type=int,
        default=100,
        help="maximum number of simultaneous client connections.")

    parser.addoption(
        "--trusted-proxy", type=str,
        help="IP address of proxy we trust. See waitress documentation.")

    parser.addoption(
        "--trusted-proxy-count", type=int,
        help="how many proxies we trust when chained. See waitress documentation.")

    parser.addoption(
        "--trusted-proxy-headers", type=str,
        help="headers to trust from proxy. See waitress documentation.")

    parser.addoption(
        "--max-request-body-size", type=int,
        default=1073741824,
        help="maximum number of bytes in request body. "
             "This controls the max size of package that can be uploaded.")

    parser.addoption(
        "--outside-url", type=str, dest="outside_url",
        metavar="URL",
        default=None,
        help="the outside URL where this server will be reachable. "
             "Set this if you proxy devpi-server through a web server "
             "and the web server does not set or you want to override "
             "the custom X-outside-url header.")

    parser.addoption(
        "--absolute-urls", action="store_true",
        help="use absolute URLs everywhere. "
             "This will become the default at some point.")

    parser.addoption(
        "--profile-requests", type=int, metavar="NUM", default=0,
        help="profile NUM requests and print out cumulative stats. "
             "After print profiling is restarted. "
             "By default no profiling is performed.")


def add_mirror_options(parser, pluginmanager):
    parser.addoption(
        "--mirror-cache-expiry", type=int, metavar="SECS",
        default=DEFAULT_MIRROR_CACHE_EXPIRY,
        help="(experimental) time after which projects in mirror indexes "
             "are checked for new releases.")


def add_replica_options(parser, pluginmanager):
    add_primary_url_option(parser, pluginmanager)

    parser.addoption(
        "--replica-max-retries", type=int, metavar="NUM",
        default=0,
        help="Number of retry attempts for replica connection failures "
             "(such as aborted connections to pypi).")

    parser.addoption(
        "--replica-file-search-path", metavar="PATH",
        help="path to existing files to try before downloading "
             "from primary. These could be from a previous "
             "replication attempt or downloaded separately. "
             "Expects the structure from previous state or +files.")

    add_hard_links_option(parser, pluginmanager)

    parser.addoption(
        "--replica-cert", action="store", dest="replica_cert",
        metavar="pem_file",
        help="when running as a replica, use the given .pem file as the "
             "SSL client certificate to authenticate to the server "
             "(EXPERIMENTAL)",
        default=None)

    parser.addoption(
        "--file-replication-threads", type=int, metavar="NUM",
        default=DEFAULT_FILE_REPLICATION_THREADS,
        help="number of threads for file download from primary")

    parser.addoption(
        "--proxy-timeout", type=int, metavar="NUM",
        default=DEFAULT_PROXY_TIMEOUT,
        help="Number of seconds to wait before proxied requests from "
             "the replica to the primary time out (login, uploads etc).")

    parser.addoption(
        "--no-replica-streaming", dest="replica_streaming",
        default=True, action="store_false",
        help="use separate requests instead of replica streaming protocol")


def add_request_options(parser, pluginmanager):
    parser.addoption(
        "--request-timeout", type=int, metavar="NUM",
        default=DEFAULT_REQUEST_TIMEOUT,
        help="Number of seconds before request being terminated "
             "(such as connections to pypi, etc.).")

    parser.addoption(
        "--offline-mode", action="store_true",
        help="(experimental) prevents connections to any upstream server "
             "(e.g. pypi) and only serves locally cached files through the "
             "simple index used by pip.")


def add_storage_options(parser, pluginmanager):
    parser.addoption(
        "--serverdir", type=str, metavar="DIR", action="store",
        default='~/.devpi/server',
        help="directory for server data.")

    storages = pluginmanager.hook.devpiserver_storage_backend(settings=None)
    backends = sorted(
        (s for s in storages if not s.get('hidden', False)),
        key=itemgetter("name"))
    parser.addoption(
        "--storage", type=str, metavar="NAME",
        action="store",
        default="sqlite",
        help="the storage backend to use.\n" + ", ".join(
             '"%s": %s' % (x['name'], x['description']) for x in backends))

    parser.addoption(
        "--keyfs-cache-size", type=int, metavar="NUM",
        action="store", default=10000,
        help="size of keyfs cache. If your devpi-server installation "
             "gets a lot of writes, then increasing this might "
             "improve performance. Each entry uses 1kb of memory on "
             "average. So by default about 10MB are used.")


def add_init_options(parser, pluginmanager):
    parser.addoption(
        "--no-root-pypi", action="store_true",
        help="don't create root/pypi on server initialization.")

    parser.addoption(
        "--root-passwd", type=str, default="",
        help="initial password for the root user. This option has no "
             "effect if the user 'root' already exist.")

    parser.addoption(
        "--root-passwd-hash", type=str, default=None,
        help="initial password hash for the root user. "
             "This option has no effect if the user 'root' already "
             "exist.")


def add_export_options(parser, pluginmanager):
    parser.addoption(
        "--include-mirrored-files", action="store_true",
        help="include downloaded files from mirror indexes in dump.")


def add_import_options(parser, pluginmanager):
    parser.addoption(
        "--skip-import-type", action="append", metavar="TYPE",
        help="skip the given index type during import. "
             "Used when the corresponding plugin isn't installed anymore.")

    parser.addoption(
        "--no-events", action="store_false",
        default=True, dest="wait_for_events",
        help="no events will be run during import, instead they are "
             "postponed to run on server start. This allows much faster "
             "start of the server after import, when devpi-web is used. "
             "When you start the server after the import, the search "
             "index and documentation will gradually update until the "
             "server has caught up with all events.")


def add_secretfile_option(parser, pluginmanager):
    parser.addoption(
        "--secretfile", type=str, metavar="path",
        help="file containing the server side secret used for user "
             "validation. If not specified, a random secret is "
             "generated on each start up.")

    parser.addoption(
        "--argon2-memory-cost", type=int, default=DEFAULT_ARGON2_MEMORY_COST,
        help=argparse.SUPPRESS)

    parser.addoption(
        "--argon2-parallelism", type=int, default=DEFAULT_ARGON2_PARALLELISM,
        help=argparse.SUPPRESS)

    parser.addoption(
        "--argon2-time-cost", type=int, default=DEFAULT_ARGON2_TIME_COST,
        help=argparse.SUPPRESS)


def add_deploy_options(parser, pluginmanager):
    add_secretfile_option(parser, pluginmanager)

    parser.addoption(
        "--requests-only", action="store_true",
        help="only start as a worker which handles read/write web requests "
             "but does not run an event processing or replication thread.")


def add_permission_options(parser, pluginmanager):
    parser.addoption(
        "--restrict-modify", type=str, metavar="SPEC",
        action="store", default=None,
        help="specify which users/groups may create other users and their "
             "indices. Multiple users and groups are separated by commas. "
             "Groups need to be prefixed with a colon like this: ':group'. "
             "By default anonymous users can create users and "
             "then create indices themself, but not modify other users "
             "and their indices. The root user can do anything. When this "
             "option is set, only the specified users/groups can create "
             "and modify users and indices. You have to add root "
             "explicitly if wanted.")


def addoptions(parser, pluginmanager):
    add_help_option(parser, pluginmanager)
    add_configfile_option(parser, pluginmanager)
    add_role_option(parser, pluginmanager)

    parser.addoption(
        "--version", action="store_true",
        help="show devpi_version (%s)" % devpi_server.__version__)

    parser.addoption(
        "--passwd", action="store", metavar="USER",
        help="(DEPRECATED, use devpi-passwd command) set password for "
             "user USER (interactive)")

    add_logging_options(
        parser.addgroup("logging options"),
        pluginmanager)
    add_web_options(
        parser.addgroup("web serving options"),
        pluginmanager)
    add_mirror_options(
        parser.addgroup("mirroring options"),
        pluginmanager)
    add_replica_options(
        parser.addgroup("replica options"),
        pluginmanager)
    add_request_options(
        parser.addgroup("request options"),
        pluginmanager)
    add_storage_options(
        parser.addgroup("storage options"),
        pluginmanager)
    add_deploy_options(
        parser.addgroup("deployment options"),
        pluginmanager)
    add_permission_options(
        parser.addgroup("permission options"),
        pluginmanager)


def try_argcomplete(parser):
    try:
        import argcomplete
    except ImportError:
        pass
    else:
        argcomplete.autocomplete(parser)


def get_parser(pluginmanager):
    parser = MyArgumentParser(
        description="Start a server which serves multiple users and "
                    "indices. The special root/pypi index is a cached "
                    "mirror of pypi.org and is created by default. "
                    "All indices are suitable for pip or easy_install usage "
                    "and setup.py upload ... invocations.",
        add_help=False,
        pluginmanager=pluginmanager)
    addoptions(parser, pluginmanager)
    pluginmanager.hook.devpiserver_add_parser_options(parser=parser)
    return parser


def find_config_file():
    import platformdirs
    config_dirs = platformdirs.site_config_dir(
        'devpi-server', 'devpi', multipath=True)
    config_dirs = config_dirs.split(os.pathsep)
    config_dirs.append(
        platformdirs.user_config_dir('devpi-server', 'devpi'))
    config_files = []
    for config_dir in config_dirs:
        config_file = os.path.join(config_dir, 'devpi-server.yml')
        if os.path.exists(config_file):
            config_files.append(config_file)
    if len(config_files) > 1:
        log.warning("Multiple configuration files found:\n%s", "\n".join(config_files))
    if not config_files:
        return None
    return config_files[-1]


class InvalidConfigError(ValueError):
    pass


def load_config_file(config_file):
    import strictyaml
    if not config_file:
        return {}
    with open(config_file, 'rb') as f:
        content = f.read().decode('utf-8')
        config = strictyaml.load(content)
        if config.is_scalar():
            return {}
        elif config.is_sequence():
            raise InvalidConfigError(
                "The config file must be a mapping, not a sequence.")
        if 'devpi-server' not in config:
            return {}
        config = config['devpi-server']
        if config.is_scalar():
            return {}
        elif config.is_sequence():
            raise InvalidConfigError(
                "The 'devpi-server' section must be a mapping, not a sequence.")
        return config.data


def default_getter(name, config_options, environ):
    if name is None:
        return
    if name == "serverdir":
        if "DEVPI_SERVERDIR" in environ:
            log.warning(
                "Using deprecated DEVPI_SERVERDIR environment variable. "
                "You should switch to use DEVPISERVER_SERVERDIR.")
            return environ["DEVPI_SERVERDIR"]
    envname = "DEVPISERVER_%s" % name.replace('-', '_').upper()
    if envname in environ:
        value = environ[envname]
        if value:
            return value
    return config_options[name]


def parseoptions(pluginmanager, argv, parser=None):
    if parser is None:
        parser = get_parser(pluginmanager)
    try_argcomplete(parser)
    # suppress any errors
    org_error = parser.error
    parser.error = lambda m: None
    args = parser.parse_args(argv[1:])
    # restore error method
    parser.error = org_error
    config_file = None
    if args.configfile:
        config_file = args.configfile
    else:
        config_file = find_config_file()
    try:
        config_options = load_config_file(config_file)
    except InvalidConfigError as e:
        log.error("Error in config file '%s':\n  %s" % (  # noqa: TRY400
            config_file, e))
        sys.exit(4)
    defaultget = partial(
        default_getter,
        config_options=config_options,
        environ=os.environ)
    parser.post_process_actions(defaultget=defaultget)
    if args.help is True:
        parser.print_help()
        parser.exit()
    args = parser.parse_args(argv[1:])
    config = Config(args, pluginmanager=pluginmanager)
    return config


def get_action_long_name(action):
    """ extract long name of action

        Looks for the first option string that is long enough and
        starts with two ``prefix_chars``.
        For example ``--no-events`` would return ``no-events``.
    """
    for option_string in action.option_strings:
        if not len(option_string) > 2:
            continue
        if option_string[0] not in action.container.prefix_chars:
            continue
        if option_string[1] not in action.container.prefix_chars:
            continue
        return option_string[2:]


class MyArgumentParser(argparse.ArgumentParser):
    def __init__(self, *args, pluginmanager=None, **kwargs):
        self.addoption = self.add_argument
        self.pluginmanager = pluginmanager
        super(MyArgumentParser, self).__init__(*args, **kwargs)

    def post_process_actions(self, defaultget=None):
        """ update default values for actions

            The passed in defaultget function is used with the long name
            of the action to look up the default value. This is used to
            get the current value if a global or user config file is loaded.
        """
        for action in self._actions:
            if defaultget is not None:
                try:
                    action.default = defaultget(get_action_long_name(action))
                except KeyError:
                    pass
                else:
                    if isinstance(action, argparse._StoreTrueAction):
                        action.default = bool(strtobool(action.default))
                    elif isinstance(action, argparse._StoreFalseAction):
                        action.default = not bool(strtobool(action.default))
            default = action.default
            if isinstance(action, argparse._StoreFalseAction):
                default = not default
            if action.help and argparse.SUPPRESS not in (action.help, default):
                action.help += " [%s]" % default

    def addgroup(self, *args, **kwargs):
        grp = super(MyArgumentParser, self).add_argument_group(*args, **kwargs)
        grp.addoption = grp.add_argument
        return grp

    def add_all_options(self):
        addoptions(self, self.pluginmanager)

    def add_configfile_option(self):
        add_configfile_option(self, self.pluginmanager)

    def add_export_options(self):
        add_export_options(self, self.pluginmanager)

    def add_hard_links_option(self):
        add_hard_links_option(self, self.pluginmanager)

    def add_help_option(self):
        add_help_option(self, self.pluginmanager)

    def add_import_options(self):
        add_import_options(self, self.pluginmanager)

    def add_init_options(self):
        add_init_options(self, self.pluginmanager)

    def add_logging_options(self) -> None:
        add_logging_options(self, self.pluginmanager)

    def add_master_url_option(self):
        warnings.warn(
            "The add_master_url_option method is deprecated, "
            "use add_primary_url_option instead",
            DeprecationWarning,
            stacklevel=2)
        add_primary_url_option(self, self.pluginmanager)

    def add_primary_url_option(self):
        add_primary_url_option(self, self.pluginmanager)

    def add_role_option(self):
        add_role_option(self, self.pluginmanager)

    def add_secretfile_option(self):
        add_secretfile_option(self, self.pluginmanager)

    def add_storage_options(self):
        add_storage_options(self, self.pluginmanager)


def new_secret():
    return base64.b64encode(secrets.token_bytes(32))


class ConfigurationError(Exception):
    """ incorrect configuration or environment settings. """


class Config(object):
    def __init__(self, args, pluginmanager):
        self.args = args
        self.pluginmanager = pluginmanager
        self.hook = pluginmanager.hook
        self._key_cache = {}

    @cached_property
    def waitress_info(self):
        from .main import Fatal
        host = self.args.host
        port = self.args.port
        default_host_port = (host == 'localhost') and (port == 3141)
        addresses = []
        kwargs = dict(
            threads=self.args.threads,
            max_request_body_size=self.args.max_request_body_size)
        unix_socket = self.args.unix_socket
        if unix_socket is not None:
            kwargs['unix_socket'] = unix_socket
            if self.args.unix_socket_perms is not None:
                kwargs['unix_socket_perms'] = self.args.unix_socket_perms
            if default_host_port:
                host = None
                port = None
        if self.args.listen:
            if not default_host_port:
                raise Fatal("You can use either --listen or --host/--port, not both together.")
            host = None
            port = None
            for listen in self.args.listen:
                kwargs.setdefault("listen", []).append(listen)
                addresses.append("http://%s" % listen)
        if host or port:
            kwargs['host'] = host
            kwargs['port'] = port
            hostaddr = "http://%s:%s" % (host, port)
            hostaddr6 = "http://[%s]:%s" % (host, port)
            addresses.append("%s (might be %s for IPv6)" % (hostaddr, hostaddr6))
        if "listen" in kwargs:
            kwargs["listen"] = " ".join(kwargs["listen"])
        if self.args.trusted_proxy is not None:
            kwargs["trusted_proxy"] = self.args.trusted_proxy
        if self.args.trusted_proxy_count is not None:
            kwargs["trusted_proxy_count"] = self.args.trusted_proxy_count
        if self.args.trusted_proxy_headers is not None:
            kwargs["trusted_proxy_headers"] = self.args.trusted_proxy_headers
        if self.args.connection_limit is not None:
            kwargs["connection_limit"] = self.args.connection_limit
        return dict(kwargs=kwargs, addresses=addresses)

    @cached_property
    def serverdir(self):
        warnings.warn(
            "The serverdir property is deprecated, "
            "use server_path instead",
            DeprecationWarning,
            stacklevel=3)
        return py.path.local(self.server_path)

    @cached_property
    def server_path(self):
        return Path(self.args.serverdir).expanduser()

    @cached_property
    def path_nodeinfo(self):
        warnings.warn(
            "The path_nodeinfo property is deprecated, "
            "use nodeinfo_path instead",
            DeprecationWarning,
            stacklevel=3)
        return py.path.local(self.nodeinfo_path)

    @cached_property
    def nodeinfo_path(self):
        return self.server_path / ".nodeinfo"

    def init_nodeinfo(self):
        log.info("Loading node info from %s", self.nodeinfo_path)
        self._determine_role()
        self._determine_uuid()
        self._determine_storage()
        self.write_nodeinfo()

    def _determine_uuid(self):
        if "uuid" not in self.nodeinfo:
            uuid_hex = uuid.uuid4().hex
            self.nodeinfo["uuid"] = uuid_hex
            threadlog.info("generated uuid: %s", uuid_hex)

    @property
    def role(self):
        role = self.nodeinfo["role"]
        if role == "master":
            warnings.warn(
                "role==master is deprecated, use primary instead.",
                DeprecationWarning,
                stacklevel=2)
            return "primary"
        return role

    def set_uuid(self, uuid):
        # called when importing state
        self.nodeinfo["uuid"] = uuid
        self.write_nodeinfo()

    def set_primary_uuid(self, uuid):
        assert self.role == "replica", "can only set primary uuid on replica"
        existing = self.get_primary_uuid()
        if existing and existing != uuid:
            raise ValueError("already have primary id %r, got %r" % (
                             existing, uuid))
        self.nodeinfo["primary-uuid"] = uuid
        self.write_nodeinfo()

    def get_master_uuid(self):
        warnings.warn(
            "get_master_uuid is deprecated, use get_primary_uuid instead",
            DeprecationWarning,
            stacklevel=2)
        return self.get_primary_uuid()

    def get_primary_uuid(self):
        if self.role != "replica":
            return self.nodeinfo["uuid"]
        if "master-uuid" in self.nodeinfo:
            warnings.warn(
                "master-uuid in nodeinfo is deprecated, use primary-uuid instead",
                DeprecationWarning,
                stacklevel=2)
            return self.nodeinfo["master-uuid"]
        return self.nodeinfo.get("primary-uuid")

    @cached_property
    def nodeinfo(self):
        if self.nodeinfo_path.is_file():
            with self.nodeinfo_path.open() as f:
                return json.load(f)
        return {}

    def write_nodeinfo(self):
        nodeinfo_dir = self.nodeinfo_path.parent
        nodeinfo_dir.mkdir(parents=True, exist_ok=True)
        prefix = "-" + self.nodeinfo_path.name
        with NamedTemporaryFile(prefix=prefix, delete=False, dir=nodeinfo_dir) as f:
            f.write(json.dumps(self.nodeinfo, indent=2).encode('utf-8'))
        fileutil.rename(f.name, self.nodeinfo_path)
        threadlog.info("wrote nodeinfo to: %s", self.nodeinfo_path)

    @property
    def master_auth(self):
        warnings.warn(
            "master_auth is deprecated, use primary_auth instead",
            DeprecationWarning,
            stacklevel=2)
        return self.primary_auth

    @property
    def master_url(self):
        warnings.warn(
            "master_url is deprecated, use primary_url instead",
            DeprecationWarning,
            stacklevel=2)
        return self.primary_url

    @property
    def primary_auth(self):
        # trigger setting of _primary_auth
        return self._primary_auth if self.primary_url else None

    @property
    def primary_url(self):
        if hasattr(self, '_primary_url'):
            return self._primary_url
        primary_url = None
        if getattr(self.args, 'deprecated_master_url', None):
            if getattr(self.args, 'primary_url', None):
                from .main import fatal
                fatal("Can't use both --master-url and --primary-url")
            warnings.warn(
                "The --master-url option is deprecated, "
                "use --primary-url instead.",
                DeprecationWarning,
                stacklevel=2)
            threadlog.warning(
                "The --master-url option is deprecated, "
                "use --primary-url instead.")
            primary_url = URL(self.args.deprecated_master_url)
        elif getattr(self.args, 'primary_url', None):
            primary_url = URL(self.args.primary_url)
        elif self.nodeinfo.get("masterurl"):
            primary_url = URL(self.nodeinfo["masterurl"])
        self.primary_url = primary_url
        return self.primary_url

    @primary_url.setter
    def primary_url(self, value):
        auth = (None, None)
        if value is not None:
            auth = (value.username, value.password)
            netloc = value.hostname
            if value.port:
                netloc = "%s:%s" % (netloc, value.port)
            value = value.replace(netloc=netloc)
        if auth == (None, None):
            auth = None
        self._primary_auth = auth
        self._primary_url = value

    @property
    def include_mirrored_files(self):
        return getattr(self.args, 'include_mirrored_files', False)

    @property
    def mirror_cache_expiry(self):
        return getattr(self.args, 'mirror_cache_expiry', DEFAULT_MIRROR_CACHE_EXPIRY)

    @property
    def no_root_pypi(self):
        return getattr(self.args, 'no_root_pypi', False)

    @property
    def offline_mode(self):
        return getattr(self.args, 'offline_mode', False)

    @property
    def file_replication_threads(self):
        return getattr(
            self.args,
            'file_replication_threads', DEFAULT_FILE_REPLICATION_THREADS)

    @property
    def hard_links(self):
        return getattr(self.args, 'hard_links', False)

    @property
    def replica_cert(self):
        return getattr(self.args, 'replica_cert', None)

    @property
    def replica_file_search_path(self):
        return getattr(self.args, 'replica_file_search_path', None)

    @property
    def replica_max_retries(self):
        return getattr(self.args, 'replica_max_retries', None)

    @property
    def replica_streaming(self):
        return getattr(self.args, 'replica_streaming', True)

    @property
    def requests_only(self):
        return getattr(self.args, 'requests_only', False)

    @property
    def request_timeout(self):
        return getattr(self.args, 'request_timeout', DEFAULT_REQUEST_TIMEOUT)

    @property
    def root_passwd(self):
        return getattr(self.args, 'root_passwd', "")

    @property
    def root_passwd_hash(self):
        return getattr(self.args, 'root_passwd_hash', None)

    @property
    def skip_import_type(self):
        return getattr(self.args, 'skip_import_type', None)

    @cached_property
    def restrict_modify(self):
        rm = self.args.restrict_modify
        if rm is not None:
            rm = frozenset(x.strip() for x in rm.split(','))
        return rm

    @property
    def wait_for_events(self):
        return getattr(self.args, 'wait_for_events', False)

    def _init_role(self):
        if self.primary_url:
            self.nodeinfo["role"] = "replica"
        else:
            self.nodeinfo["role"] = "standalone"

    def _automatic_role(self, role):
        from .main import Fatal
        if role == "replica" and not self.primary_url:
            raise Fatal(
                "configuration error, primary URL isn't set in nodeinfo, but "
                "role is set to replica")
        if role != "replica" and self.primary_url:
            raise Fatal(
                "configuration error, primary URL set in nodeinfo, but role "
                "isn't set to replica")
        if role != "replica":
            self.primary_url = None
        if role in ("master", "primary"):
            # we only allow explicit primary role
            self.nodeinfo["role"] = "standalone"

    def _change_role(self, old_role, new_role):
        from .main import Fatal
        if new_role == "replica":
            if old_role and old_role != "replica":
                msg = f"cannot run as replica, was previously run as {old_role}"
                raise Fatal(msg)
            if not self.primary_url:
                raise Fatal("need to specify --primary-url to run as replica")
        else:
            self.primary_url = None
        self.nodeinfo["role"] = new_role

    def _determine_role(self):
        role = getattr(self.args, "role", "auto")
        old_role = self.nodeinfo.get("role")
        if role == "auto" and not old_role:
            self._init_role()
        elif role == "auto":
            self._automatic_role(old_role)
        elif old_role != role:
            self._change_role(old_role, role)
        assert self.nodeinfo["role"]
        if self.nodeinfo["role"] == "replica":
            assert self.primary_url
        if self.primary_url:
            self.nodeinfo["masterurl"] = self.primary_url.url
        else:
            self.nodeinfo.pop("masterurl", None)

    def _storage_info_from_name(self, name, settings):
        from .main import Fatal
        storages = self.pluginmanager.hook.devpiserver_storage_backend(settings=settings)
        for storage in storages:
            if storage['name'] == name:
                return storage
        msg = f"The backend {name!r} can't be found, is the plugin not installed?"
        raise Fatal(msg)

    def _storage_info(self):
        name = self.storage_info["name"]
        settings = self.storage_info["settings"]
        return self._storage_info_from_name(name, settings)

    @property
    def storage(self):
        return self._storage_info()["storage"]

    def _determine_storage(self):
        if isinstance(self.args.storage, dict):
            # a yaml config may return a dict
            settings = dict(self.args.storage)
            name = settings.pop('name')
        else:
            name, sep, setting_str = self.args.storage.partition(':')
            settings = {}
            if setting_str:
                for item in setting_str.split(','):
                    key, value = item.split('=', 1)
                    settings[key] = value
        storage_info = self._storage_info_from_name(name, settings)
        self.storage_info = dict(
            name=storage_info['name'],
            settings=settings)

    def sqlite_file_needed_but_missing(self):
        return (
            self.storage_info['name'] == 'sqlite'
            and not self.server_path.joinpath(".sqlite").exists()
        )

    @cached_property
    def secretfile(self):
        warnings.warn(
            "The secretfile property is deprecated, "
            "use secret_path instead",
            DeprecationWarning,
            stacklevel=3)
        return py.path.local(self.secret_path)

    @cached_property
    def secret_path(self):
        if not self.args.secretfile:
            secretfile = self.server_path / '.secret'
            if not secretfile.is_file():
                return None
            log.warning(
                "Using deprecated existing secret file at '%s', use "
                "--secretfile to explicitly provide the location." % secretfile)
            return secretfile
        return Path(self.args.secretfile).expanduser()

    def get_validated_secret(self):
        from .main import Fatal
        import stat
        secret_path = self.secret_path
        if not secret_path.is_file():
            raise Fatal("The given secret file doesn't exist.")
        if secret_path.stat().st_mode & stat.S_IRWXO and sys.platform != "win32":
            raise Fatal("The given secret file is world accessible, the access mode must be user accessible only (0600).")
        if secret_path.stat().st_mode & stat.S_IRWXG and sys.platform != "win32":
            raise Fatal("The given secret file is group accessible, the access mode must be user accessible only (0600).")
        if secret_path.parent.stat().st_mode & stat.S_IWGRP and sys.platform != "win32":
            raise Fatal("The folder of the given secret file is group writable, it must only be writable by the user.")
        if secret_path.parent.stat().st_mode & stat.S_IWOTH and sys.platform != "win32":
            raise Fatal("The folder of the given secret file is world writable, it must only be writable by the user.")
        secret = secret_path.read_bytes()
        if len(secret) < 32:
            raise Fatal(
                "The secret in the given secret file is too short, "
                "it should be at least 32 characters long.")
        if len(set(secret)) < 6:
            raise Fatal(
                "The secret in the given secret file is too weak, "
                "it should use less repetition.")
        return secret

    @cached_property
    def basesecret(self):
        if self.secret_path is None:
            log.warning(
                "No secret file provided, creating a new random secret. "
                "Login tokens issued before are invalid. "
                "Use --secretfile option to provide a persistent secret. "
                "You can create a proper secret with the "
                "devpi-gen-secret command.")
            return new_secret()
        secret = self.get_validated_secret()
        log.info("Using secret file '%s'.", self.secret_path)
        return secret

    @property
    def _secret_parameters(self):
        # this is a property, so it can easily be changed for tests
        # see lower_argon2_parameters fixture
        return argon2.Parameters(
            type=argon2.low_level.Type.ID,
            version=argon2.low_level.ARGON2_VERSION,
            salt_len=16,
            hash_len=16,
            time_cost=self.args.argon2_time_cost,
            memory_cost=self.args.argon2_memory_cost,
            parallelism=self.args.argon2_parallelism)

    def get_derived_key(self, salt):
        if salt not in self._key_cache:
            secret_parameters = self._secret_parameters
            self._key_cache[salt] = argon2.low_level.hash_secret_raw(
                self.basesecret,
                salt,
                time_cost=secret_parameters.time_cost,
                memory_cost=secret_parameters.memory_cost,
                parallelism=secret_parameters.parallelism,
                hash_len=secret_parameters.hash_len,
                type=secret_parameters.type,
                version=secret_parameters.version)
        return self._key_cache[salt]

    def get_auth_secret(self):
        return self.get_derived_key(b'devpi-server-auth')

    def get_replica_secret(self):
        return self.get_derived_key(b'devpi-server-replica')


def gensecret():
    from .log import threadlog as log
    from .main import CommandRunner
    from .main import Fatal
    import stat
    with CommandRunner() as runner:
        parser = runner.create_parser(
            description="Create a random secret.",
            add_help=False)
        parser.add_help_option()
        parser.add_configfile_option()
        parser.add_logging_options()
        parser.add_secretfile_option()
        config = runner.get_config(sys.argv, parser=parser)
        runner.configure_logging(config.args)
        if config.args.secretfile is None:
            raise Fatal("You need to provide a location for the secret file.")
        if not config.secret_path.exists():
            config.secret_path.write_bytes(new_secret())
            log.info("New secret written to '%s'" % config.secret_path)
            if sys.platform != "win32":
                mode = config.secret_path.stat().st_mode
                if mode & stat.S_IRWXG or mode & stat.S_IRWXO:
                    config.secret_path.chmod(0o600)
                    log.info("Changed file mode to 0600 to adjust access permissions.")
        else:
            log.info("Checking existing secret at '%s'" % config.secret_path)
        # run checks
        config.get_validated_secret()
        log.info("Permissions of secret file look good.")
    return runner.return_code
