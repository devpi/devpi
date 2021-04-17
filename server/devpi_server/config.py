from __future__ import unicode_literals
import argon2
import base64
import os.path
import argparse
import secrets
import sys
import uuid
from operator import itemgetter
from tempfile import NamedTemporaryFile
from pluggy import HookimplMarker, PluginManager
import py
from devpi_common.types import cached_property
from distutils.util import strtobool
from functools import partial
from .log import threadlog
from . import hookspecs
import json
import devpi_server
from devpi_common.url import URL

log = threadlog


hookimpl = HookimplMarker("devpiserver")


DEFAULT_MIRROR_CACHE_EXPIRY = 1800
DEFAULT_PROXY_TIMEOUT = 30
DEFAULT_REQUEST_TIMEOUT = 5
DEFAULT_FILE_REPLICATION_THREADS = 5
DEFAULT_ARGON2_MEMORY_COST = 524288
DEFAULT_ARGON2_PARALLELISM = 8
DEFAULT_ARGON2_TIME_COST = 16


def get_pluginmanager(load_entrypoints=True):
    pm = PluginManager("devpiserver")
    # support old plugins, but emit deprecation warnings
    pm._implprefix = "devpiserver_"
    pm.add_hookspecs(hookspecs)
    # XXX load internal plugins here
    if load_entrypoints:
        pm.load_setuptools_entrypoints("devpi_server")
    pm.check_pending()
    return pm


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
        choices=["master", "replica", "standalone", "auto"],
        help="set role of this instance. The default 'auto' sets "
             "'standalone' by default and 'replica' if the --master-url "
             "option is used. To enable the replication protocol you have "
             "to explicitly set the 'master' role.")


def add_master_url_option(parser, pluginmanager):
    parser.addoption(
        "--master-url", action="store", dest="master_url",
        help="run as a replica of the specified master server",
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
        "--mirror-cache-expiry", type=float, metavar="SECS",
        default=DEFAULT_MIRROR_CACHE_EXPIRY,
        help="(experimental) time after which projects in mirror indexes "
             "are checked for new releases.")


def add_replica_options(parser, pluginmanager):
    add_master_url_option(parser, pluginmanager)

    parser.addoption(
        "--replica-max-retries", type=int, metavar="NUM",
        default=0,
        help="Number of retry attempts for replica connection failures "
             "(such as aborted connections to pypi).")

    parser.addoption(
        "--replica-file-search-path", metavar="PATH",
        help="path to existing files to try before downloading "
             "from master. These could be from a previous "
             "replication attempt or downloaded separately. "
             "Expects the structure from inside +files.")

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
        help="number of threads for file download from master")

    parser.addoption(
        "--proxy-timeout", type=int, metavar="NUM",
        default=DEFAULT_PROXY_TIMEOUT,
        help="Number of seconds to wait before proxied requests from "
             "the replica to the master time out (login, uploads etc).")


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

    backends = sorted(
        pluginmanager.hook.devpiserver_storage_backend(settings=None),
        key=itemgetter("name"))
    parser.addoption(
        "--storage", type=str, metavar="NAME",
        action="store",
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


def add_deploy_options(parser, pluginmanager):
    add_secretfile_option(parser, pluginmanager)

    parser.addoption(
        "--argon2-memory-cost", type=int, default=DEFAULT_ARGON2_MEMORY_COST,
        help="Argon2 memory cost parameter for key derivation. "
             "This is *not* for the user password hashes. "
             "There should be no need to touch this setting, "
             "except you really know what this is about! "
             "Replicas need to use the same parameters as the master.")

    parser.addoption(
        "--argon2-parallelism", type=int, default=DEFAULT_ARGON2_PARALLELISM,
        help="Argon2 parallelism parameter for key derivation. "
             "This is *not* for the user password hashes. "
             "There should be no need to touch this setting, "
             "except you really know what this is about! "
             "Replicas need to use the same parameters as the master.")

    parser.addoption(
        "--argon2-time-cost", type=int, default=DEFAULT_ARGON2_TIME_COST,
        help="Argon2 time cost parameter for key derivation. "
             "This is *not* for the user password hashes. "
             "There should be no need to touch this setting, "
             "except you really know what this is about! "
             "Replicas need to use the same parameters as the master.")

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
             "explicitely if wanted.")


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
        add_help=False)
    addoptions(parser, pluginmanager)
    pluginmanager.hook.devpiserver_add_parser_options(parser=parser)
    return parser


def find_config_file():
    import appdirs
    config_dirs = appdirs.site_config_dir(
        'devpi-server', 'devpi', multipath=True)
    config_dirs = config_dirs.split(os.pathsep)
    config_dirs.append(
        appdirs.user_config_dir('devpi-server', 'devpi'))
    config_files = []
    for config_dir in config_dirs:
        config_file = os.path.join(config_dir, 'devpi-server.yml')
        if os.path.exists(config_file):
            config_files.append(config_file)
    if len(config_files) > 1:
        log.warn("Multiple configuration files found:\n%s", "\n".join(config_files))
    if len(config_files):
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
            log.warn(
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
        log.error("Error in config file '%s':\n  %s" % (
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
    def __init__(self, *args, **kwargs):
        self.addoption = self.add_argument
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
            if action.help and action.default != '==SUPPRESS==':
                action.help += " [%s]" % default

    def addgroup(self, *args, **kwargs):
        grp = super(MyArgumentParser, self).add_argument_group(*args, **kwargs)
        grp.addoption = grp.add_argument
        return grp


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
        from .main import fatal
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
                fatal("You can use either --listen or --host/--port, not both together.")
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
        return dict(kwargs=kwargs, addresses=addresses)

    @cached_property
    def serverdir(self):
        return py.path.local(os.path.expanduser(self.args.serverdir))

    @cached_property
    def path_nodeinfo(self):
        return self.serverdir.join(".nodeinfo")

    def init_nodeinfo(self):
        log.info("Loading node info from %s", self.path_nodeinfo)
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
        return self.nodeinfo["role"]

    def set_uuid(self, uuid):
        # called when importing state
        self.nodeinfo["uuid"] = uuid
        self.write_nodeinfo()

    def set_master_uuid(self, uuid):
        assert self.role == "replica", "can only set master uuid on replica"
        existing = self.nodeinfo.get("master-uuid")
        if existing and existing != uuid:
            raise ValueError("already have master id %r, got %r" % (
                             existing, uuid))
        self.nodeinfo["master-uuid"] = uuid
        self.write_nodeinfo()

    def get_master_uuid(self):
        if self.role != "replica":
            return self.nodeinfo["uuid"]
        return self.nodeinfo.get("master-uuid")

    @cached_property
    def nodeinfo(self):
        if self.path_nodeinfo.exists():
            return json.loads(self.path_nodeinfo.read("r"))
        return {}

    def write_nodeinfo(self):
        nodeinfo_dir = self.path_nodeinfo.dirpath()
        nodeinfo_dir.ensure(dir=1)
        prefix = "-" + self.path_nodeinfo.basename
        with NamedTemporaryFile(prefix=prefix, delete=False, dir=nodeinfo_dir.strpath) as f:
            f.write(json.dumps(self.nodeinfo, indent=2).encode('utf-8'))
        try:
            os.remove(self.path_nodeinfo.strpath)
        except FileNotFoundError:
            pass
        os.rename(f.name, self.path_nodeinfo.strpath)
        threadlog.info("wrote nodeinfo to: %s", self.path_nodeinfo)

    @property
    def master_url(self):
        if hasattr(self, '_master_url'):
            return self._master_url
        master_url = None
        if getattr(self.args, 'master_url', None):
            master_url = URL(self.args.master_url)
        elif self.nodeinfo.get("masterurl"):
            master_url = URL(self.nodeinfo["masterurl"])
        self.master_url = master_url
        return self.master_url

    @master_url.setter
    def master_url(self, value):
        auth = (None, None)
        if value is not None:
            auth = (value.username, value.password)
            netloc = value.hostname
            if value.port:
                netloc = "%s:%s" % (netloc, value.port)
            value = value.replace(netloc=netloc)
        if auth == (None, None):
            auth = None
        self.master_auth = auth
        self._master_url = value

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
        if self.master_url:
            self.nodeinfo["role"] = "replica"
        else:
            self.nodeinfo["role"] = "standalone"

    def _automatic_role(self, role):
        from .main import fatal
        if role == "replica" and not self.master_url:
            fatal("configuration error, masterurl isn't set in nodeinfo, but "
                  "role is set to replica")
        if role != "replica" and self.master_url:
            fatal("configuration error, masterurl set in nodeinfo, but role "
                  "isn't set to replica")
        if role != "replica":
            self.master_url = None
        if role == "master":
            # we only allow explicit master role
            self.nodeinfo["role"] = "standalone"

    def _change_role(self, old_role, new_role):
        from .main import fatal
        if new_role == "replica":
            if old_role and old_role != "replica":
                fatal("cannot run as replica, was previously run "
                      "as %s" % old_role)
            if not self.master_url:
                fatal("need to specify --master-url to run as replica")
        else:
            self.master_url = None
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
            assert self.master_url
        if self.master_url:
            self.nodeinfo["masterurl"] = self.master_url.url
        else:
            self.nodeinfo.pop("masterurl", None)

    def _storage_info_from_name(self, name, settings):
        from .main import fatal
        storages = self.pluginmanager.hook.devpiserver_storage_backend(settings=settings)
        for storage in storages:
            if storage['name'] == name:
                return storage
        fatal("The backend '%s' can't be found, is the plugin not installed?" % name)

    def _storage_info(self):
        name = self.storage_info["name"]
        settings = self.storage_info["settings"]
        return self._storage_info_from_name(name, settings)

    @property
    def storage(self):
        return self._storage_info()["storage"]

    def _determine_storage(self):
        if self.args.storage:
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
        else:
            name = "sqlite"
            settings = {}
        storage_info = self._storage_info_from_name(name, settings)
        self.storage_info = dict(
            name=storage_info['name'],
            settings=settings)

    def sqlite_file_needed_but_missing(self):
        return (
            self.storage_info['name'] == 'sqlite'
            and not self.serverdir.join(".sqlite").exists()
        )

    @cached_property
    def secretfile(self):
        import warnings
        if not self.args.secretfile:
            secretfile = self.serverdir.join('.secret')
            if not secretfile.check(file=True):
                return None
            warnings.warn(
                "Using deprecated existing secret file at '%s', use "
                "--secretfile to explicitly provide the location." % secretfile)
            return secretfile
        return py.path.local(
            os.path.expanduser(self.args.secretfile))

    def get_validated_secret(self):
        from .main import fatal
        import stat
        if not self.secretfile.check(file=True):
            fatal("The given secret file doesn't exist.")
        if self.secretfile.stat().mode & stat.S_IRWXO and sys.platform != "win32":
            fatal("The given secret file is world accessible, the access mode must be user accessible only (0600).")
        if self.secretfile.stat().mode & stat.S_IRWXG and sys.platform != "win32":
            fatal("The given secret file is group accessible, the access mode must be user accessible only (0600).")
        if self.secretfile.dirpath().stat().mode & stat.S_IWGRP and sys.platform != "win32":
            fatal("The folder of the given secret file is group writable, it must only be writable by the user.")
        if self.secretfile.dirpath().stat().mode & stat.S_IWOTH and sys.platform != "win32":
            fatal("The folder of the given secret file is world writable, it must only be writable by the user.")
        secret = self.secretfile.read_binary()
        if len(secret) < 32:
            fatal(
                "The secret in the given secret file is too short, "
                "it should be at least 32 characters long.")
        if len(set(secret)) < 6:
            fatal(
                "The secret in the given secret file is too weak, "
                "it should use less repetition.")
        return secret

    @cached_property
    def basesecret(self):
        if self.secretfile is None:
            log.warn(
                "No secret file provided, creating a new random secret. "
                "Login tokens issued before are invalid. "
                "Use --secretfile option to provide a persistent secret. "
                "You can create a proper secret with the "
                "devpi-gen-secret command.")
            return new_secret()
        secret = self.get_validated_secret()
        log.info("Using secret file '%s'.", self.secretfile)
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


def getpath(path):
    return py.path.local(os.path.expanduser(str(path)))


def gensecret():
    from .log import configure_cli_logging
    from .log import threadlog as log
    from .main import Fatal
    from .main import fatal
    import stat
    try:
        pluginmanager = get_pluginmanager()
        parser = MyArgumentParser(
            description="Create a random secret.",
            add_help=False)
        add_help_option(parser, pluginmanager)
        add_configfile_option(parser, pluginmanager)
        add_secretfile_option(parser, pluginmanager)
        config = parseoptions(pluginmanager, sys.argv, parser=parser)
        configure_cli_logging(config.args)
        if config.args.secretfile is None:
            fatal("You need to provide a location for the secret file.")
        if not config.secretfile.exists():
            with config.secretfile.open("wb") as f:
                f.write(new_secret())
            log.info("New secret written to '%s'" % config.secretfile)
            if sys.platform != "win32":
                mode = config.secretfile.stat().mode
                if mode & stat.S_IRWXG or mode & stat.S_IRWXO:
                    config.secretfile.chmod(0o600)
                    log.info("Changed file mode to 0600 to adjust access permissions.")
        else:
            log.info("Checking existing secret at '%s'" % config.secretfile)
        # run checks
        config.get_validated_secret()
        log.info("Permissions of secret file look good.")
    except Fatal as e:
        tw = py.io.TerminalWriter(sys.stderr)
        tw.line("fatal: %s" % e.args[0], red=True)
        return 1
