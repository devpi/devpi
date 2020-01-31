from __future__ import unicode_literals
import base64
import os.path
import argparse
import sys
import uuid
from operator import itemgetter

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


def add_init_options(parser, pluginmanager, standalone=True):
    if not standalone:
        parser.addoption(
            "--init", action="store_true",
            help="(DEPRECATED, use devpi-init command) initialize "
                 "devpi-server state in an empty directory "
                 "(also see --serverdir)")

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


def add_export_options(parser, pluginmanager, standalone=True):
    if not standalone:
        parser.addoption(
            "--export", type=str, metavar="PATH",
            help="(DEPRECATED, use devpi-passwd command) export "
                 "devpi-server database state into PATH. "
                 "This will export all users, indices, release files "
                 "(except for mirrors), test results and documentation.")

    parser.addoption(
        "--include-mirrored-files", action="store_true",
        help="include downloaded files from mirror indexes in dump.")


def add_import_options(parser, pluginmanager, standalone=True):
    if not standalone:
        parser.addoption(
            "--import", type=str, metavar="PATH",
            dest="import_",
            help="(DEPRECATED, use devpi-import command) import "
                 "devpi-server database from PATH where PATH "
                 "is a directory which was created by a "
                 "'devpi-server --export PATH' operation, "
                 "using the same or an earlier devpi-server version. "
                 "Note that you can only import into a fresh server "
                 "state directory (positional argument to devpi-server).")

    parser.addoption(
        "--skip-import-type", action="append", metavar="TYPE",
        help="skip the given index type during import. "
             "Used when the corresponding plugin isn't installed anymore.")

    parser.addoption(
        "--no-events", action="store_false",
        default=True, dest="wait_for_events",
        help="no events will be run during import, instead they are"
             "postponed to run on server start. This allows much faster "
             "start of the server after import, when devpi-web is used. "
             "When you start the server after the import, the search "
             "index and documentation will gradually update until the "
             "server has caught up with all events.")


def add_deploy_options(parser, pluginmanager):
    parser.addoption(
        "--gen-config", dest="genconfig", action="store_true",
        help="(DEPRECATED, use devpi-gen-config command) "
             "generate example config files for "
             "nginx/supervisor/crontab/systemd/launchd/windows-service, "
             "taking other passed options into account "
             "(e.g. port, host, etc.)")

    parser.addoption(
        "--secretfile", type=str, metavar="path",
        help="file containing the server side secret used for user "
             "validation. If not specified, a random secret is "
             "generated on each start up. ")

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
    add_init_options(
        parser.addgroup("initialization options"),
        pluginmanager, standalone=False)
    add_import_options(
        parser.addgroup("serverstate import options"),
        pluginmanager, standalone=False)
    add_export_options(
        parser.addgroup("serverstate export options"),
        pluginmanager, standalone=False)
    add_deploy_options(
        parser.addgroup("deployment options"),
        pluginmanager)
    add_permission_options(
        parser.addgroup("permission options"),
        pluginmanager)

    bg = parser.addgroup(
        "background server (DEPRECATED, see --gen-config to use a process "
        "manager from your OS)")
    bg.addoption("--start", action="store_true",
            help="start the background devpi-server")
    bg.addoption("--stop", action="store_true",
            help="stop the background devpi-server")
    bg.addoption("--status", action="store_true",
            help="show status of background devpi-server")
    bg.addoption("--log", action="store_true",
            help="show logfile content of background server")


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


class ConfigurationError(Exception):
    """ incorrect configuration or environment settings. """


class Config(object):
    def __init__(self, args, pluginmanager):
        self.args = args
        self.pluginmanager = pluginmanager
        self.hook = pluginmanager.hook
        self.serverdir = py.path.local(os.path.expanduser(self.args.serverdir))
        self.path_nodeinfo = self.serverdir.join(".nodeinfo")

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
        self.path_nodeinfo.dirpath().ensure(dir=1)
        self.path_nodeinfo.write(json.dumps(self.nodeinfo, indent=2))
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
        self.master_auth = auth
        self._master_url = value

    @property
    def mirror_cache_expiry(self):
        return getattr(self.args, 'mirror_cache_expiry', DEFAULT_MIRROR_CACHE_EXPIRY)

    @property
    def offline_mode(self):
        return getattr(self.args, 'offline_mode', False)

    @property
    def replica_cert(self):
        return getattr(self.args, 'replica_cert', None)

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
    def restrict_modify(self):
        rm = self.args.restrict_modify
        if rm is not None:
            rm = set(x.strip() for x in rm.split(','))
        return rm

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
            not getattr(self.args, 'init', None)
            and not getattr(self.args, 'import_', None)
            and self.storage_info['name'] == 'sqlite'
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

    @cached_property
    def secret(self):
        from .main import fatal
        if self.secretfile is None:
            log.warn(
                "No secret file provided, creating a new random secret. "
                "Login tokens issued before are invalidate. "
                "Use --secretfile option to provide a persistent secret.")
            return base64.b64encode(os.urandom(32))
        if not self.secretfile.check(file=True):
            fatal("The given secret file doesn't exist.")
        log.info("Using secret file '%s'.", self.secretfile)
        return self.secretfile.read()


def getpath(path):
    return py.path.local(os.path.expanduser(str(path)))

def render(tw, confname, format=None, **kw):
    result = render_string(confname, format=format, **kw)
    return result

def render_string(confname, format=None, **kw):
    template = confname + ".template"
    from pkg_resources import resource_string
    templatestring = resource_string("devpi_server.cfg", template)
    if not py.builtin._istext(templatestring):
        templatestring = py.builtin._totext(templatestring, "utf-8")

    kw = dict((x[0], str(x[1])) for x in kw.items())
    if format is None:
        result = templatestring.format(**kw)
    else:
        result = templatestring % kw
    return result
