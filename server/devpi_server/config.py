from __future__ import unicode_literals
import base64
import os.path
import argparse
import uuid
from operator import itemgetter

from pluggy import PluginManager
import py
from devpi_common.types import cached_property
from .log import threadlog
from . import hookspecs
import json
import devpi_server
from devpi_common.url import URL

log = threadlog

def get_pluginmanager(load_entrypoints=True):
    pm = PluginManager("devpiserver", implprefix="devpiserver_")
    pm.add_hookspecs(hookspecs)
    # XXX load internal plugins here
    if load_entrypoints:
        pm.load_setuptools_entrypoints("devpi_server")
    pm.check_pending()
    return pm


def get_default_serverdir():
    return os.environ.get("DEVPI_SERVERDIR", "~/.devpi/server")


def addoptions(parser, pluginmanager):
    web = parser.addgroup("web serving options")
    web.addoption("--host",  type=str,
            default="localhost",
            help="domain/ip address to listen on.  Use --host=0.0.0.0 if "
                 "you want to accept connections from anywhere.")

    web.addoption("--port",  type=int,
            default=3141,
            help="port to listen for http requests.")

    web.addoption("--outside-url",  type=str, dest="outside_url",
            metavar="URL",
            default=None,
            help="the outside URL where this server will be reachable. "
                 "Set this if you proxy devpi-server through a web server "
                 "and the web server does not set or you want to override "
                 "the custom X-outside-url header.")

    web.addoption("--debug", action="store_true",
            help="run wsgi application with debug logging")

    web.addoption("--profile-requests", type=int, metavar="NUM", default=0,
            help="profile NUM requests and print out cumulative stats. "
                 "After print profiling is restarted. "
                 "By default no profiling is performed.")

    web.addoption("--logger-cfg", action="store", dest="logger_cfg",
            help="path to .json or .yaml logger configuration file, "
                 "requires at least python2.7. If you specify a yaml "
                 "file you need to have the pyyaml package installed.",
            default=None)

    mirror = parser.addgroup("mirroring options")
    mirror.addoption("--bypass-cdn", action="store_true",
            help="set this if you want to bypass pypi's CDN for access to "
                 "simple pages and packages, in order to rule out cache-"
                 "invalidation issues.  This will only work if you "
                 "are not using a http proxy.")

    mirror.addoption("--mirror-cache-expiry", type=float, metavar="SECS",
            default=1800,
            help="(experimental) time after which projects in mirror indexes "
                 "are checked for new releases.")

    mirror.addoption("--offline-mode", action="store_true",
            help="(experimental) prevents connections to any upstream server "
                 "(e.g. pypi) and only serves locally cached files through the "
                 "simple index used by pip.")

    mirror.addoption("--no-root-pypi", action="store_true",
            help="don't create root/pypi on server initialization.")

    deploy = parser.addgroup("deployment and data options")

    deploy.addoption("--version", action="store_true",
            help="show devpi_version (%s)" % devpi_server.__version__)

    deploy.addoption("--role", action="store", dest="role", default="auto",
            choices=["master", "replica", "auto"],
            help="set role of this instance."
    )

    deploy.addoption("--master-url", action="store", dest="master_url",
            help="run as a replica of the specified master server",
            default=None)

    deploy.addoption("--replica-cert", action="store", dest="replica_cert",
            metavar="pem_file",
            help="when running as a replica, use the given .pem file as the "
                 "SSL client certificate to authenticate to the server "
                 "(EXPERIMENTAL)",
            default=None)

    deploy.addoption("--gen-config", dest="genconfig", action="store_true",
            help="(unix only ) generate example config files for "
                 "nginx/supervisor/crontab/systemd, taking other passed "
                 "options into account (e.g. port, host, etc.)"
    )

    deploy.addoption("--secretfile", type=str, metavar="path",
            default="{serverdir}/.secret",
            help="file containing the server side secret used for user "
                 "validation. If it does not exist, a random secret "
                 "is generated on start up and used subsequently. ")

    deploy.addoption("--requests-only", action="store_true",
            help="only start as a worker which handles read/write web requests "
                 "but does not run an event processing or replication thread.")

    deploy.addoption("--passwd", action="store", metavar="USER",
            help="set password for user USER (interactive)")

    deploy.addoption("--serverdir", type=str, metavar="DIR", action="store",
            default=None,
            help="directory for server data.  By default, "
                 "$DEVPI_SERVERDIR is used if it exists, "
                 "otherwise the default is '~/.devpi/server'")

    deploy.addoption("--restrict-modify", type=str, metavar="SPEC",
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

    deploy.addoption("--keyfs-cache-size", type=int, metavar="NUM",
            action="store", default=10000,
            help="size of keyfs cache. If your devpi-server installation "
                 "gets a lot of writes, then increasing this might "
                 "improve performance. Each entry uses 1kb of memory on "
                 "average. So by default about 10MB are used.")

    backends = sorted(
        pluginmanager.hook.devpiserver_storage_backend(settings=None),
        key=itemgetter("name"))
    deploy.addoption("--storage", type=str, metavar="NAME",
            action="store",
            help="the storage backend to use. This choice will be stored in "
                 "your '--serverdir' upon initialization.\n" + ", ".join(
                 '"%s": %s' % (x['name'], x['description']) for x in backends))

    expimp = parser.addgroup("serverstate export / import options")
    expimp.addoption("--export", type=str, metavar="PATH",
            help="export devpi-server database state into PATH. "
                 "This will export all users, indices, release files "
                 "(except for mirrors), test results and documentation.")

    expimp.addoption("--hard-links", action="store_true",
            help="use hard links during export instead of copying files. "
                 "All limitations for hard links on your OS apply. "
                 "USE AT YOUR OWN RISK"
    )
    expimp.addoption("--import", type=str, metavar="PATH",
            dest="import_",
            help="import devpi-server database from PATH where PATH "
                 "is a directory which was created by a "
                 "'devpi-server --export PATH' operation, "
                 "using the same or an earlier devpi-server version. "
                 "Note that you can only import into a fresh server "
                 "state directory (positional argument to devpi-server).")

    expimp.addoption("--no-events", action="store_false",
            default=True, dest="wait_for_events",
            help="no events will be run during import, instead they are"
                 "postponed to run on server start. This allows much faster "
                 "start of the server after import, when devpi-web is used. "
                 "When you start the server after the import, the search "
                 "index and documentation will gradually update until the "
                 "server has caught up with all events.")

    bg = parser.addgroup("background server")
    bg.addoption("--start", action="store_true",
            help="start the background devpi-server")
    bg.addoption("--stop", action="store_true",
            help="stop the background devpi-server")
    bg.addoption("--status", action="store_true",
            help="show status of background devpi-server")
    bg.addoption("--log", action="store_true",
            help="show logfile content of background server")
    #group.addoption("--pidfile", action="store",
    #        help="set pid file location")
    #group.addoption("--logfile", action="store",
    #        help="set log file file location")

def try_argcomplete(parser):
    try:
        import argcomplete
    except ImportError:
        pass
    else:
        argcomplete.autocomplete(parser)

def parseoptions(pluginmanager, argv, addoptions=addoptions):
    parser = MyArgumentParser(
        description="Start a server which serves multiple users and "
                    "indices. The special root/pypi index is a cached "
                    "mirror of pypi.python.org and is created by default. "
                    "All indices are suitable for pip or easy_install usage "
                    "and setup.py upload ... invocations."
    )
    addoptions(parser, pluginmanager)
    pluginmanager.hook.devpiserver_add_parser_options(parser=parser)

    try_argcomplete(parser)
    raw = [str(x) for x in argv[1:]]
    args = parser.parse_args(raw)
    args._raw = raw
    config = Config(args, pluginmanager=pluginmanager)
    return config

class MyArgumentParser(argparse.ArgumentParser):
    def __init__(self, *args, **kwargs):
        if "defaultget" in kwargs:
            self._defaultget = kwargs.pop("defaultget")
        else:
            self._defaultget = {}.__getitem__
        super(MyArgumentParser, self).__init__(*args, **kwargs)

    def addoption(self, *args, **kwargs):
        opt = super(MyArgumentParser, self).add_argument(*args, **kwargs)
        self._processopt(opt)
        return opt

    def _processopt(self, opt):
        try:
            opt.default = self._defaultget(opt.dest)
        except KeyError:
            pass
        if opt.help and opt.default:
            opt.help += " [%s]" % opt.default

    def addgroup(self, *args, **kwargs):
        grp = super(MyArgumentParser, self).add_argument_group(*args, **kwargs)
        def group_addoption(*args2, **kwargs2):
            opt = grp.add_argument(*args2, **kwargs2)
            self._processopt(opt)
            return opt
        grp.addoption = group_addoption
        return grp


class ConfigurationError(Exception):
    """ incorrect configuration or environment settings. """


class Config:
    def __init__(self, args, pluginmanager):
        self.args = args
        self.pluginmanager = pluginmanager
        self.hook = pluginmanager.hook
        serverdir = args.serverdir
        if serverdir is None:
            serverdir = get_default_serverdir()
        self.serverdir = py.path.local(os.path.expanduser(serverdir))

        if args.secretfile == "{serverdir}/.secret":
            self.secretfile = self.serverdir.join(".secret")
        else:
            self.secretfile = py.path.local(
                    os.path.expanduser(args.secretfile))

        self.path_nodeinfo = self.serverdir.join(".nodeinfo")

    def init_nodeinfo(self):
        log.info("Loading node info from %s", self.path_nodeinfo)
        self._determine_roles()
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
        assert self.role != "master", "cannot set master uuid for master"
        existing = self.nodeinfo.get("master-uuid")
        if existing and existing != uuid:
            raise ValueError("already have master id %r, got %r" % (
                             existing, uuid))
        self.nodeinfo["master-uuid"] = uuid
        self.write_nodeinfo()

    def get_master_uuid(self):
        if self.role == "master":
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

    def _determine_roles(self):
        from .main import fatal
        args = self.args
        old_role = self.nodeinfo.get("role")
        if args.master_url:
            self.master_url = URL(args.master_url)
            if old_role == "master":
                fatal("cannot run as replica, was previously run as master")
            if args.role == "master":
                fatal("option conflict: --role=master and --master-url")
            role = "replica"
            self.nodeinfo["masterurl"] = self.master_url.url
        else:
            if args.role == "replica":
                fatal("need to specify --master-url to run as replica")
            role = "master"
        if role == "master" and old_role == "replica" and \
           args.role != "master":
            fatal("need to specify --role=master to run previous replica "
                  "as a master")
        self.nodeinfo["role"] = role
        return

    def _storage_info_from_name(self, name, settings):
        from .main import fatal
        storages = self.pluginmanager.hook.devpiserver_storage_backend(settings=settings)
        for storage in storages:
            if storage['name'] == name:
                return storage
        fatal("The backend '%s' can't be found, is the plugin not installed?" % name)

    def _storage_info(self):
        name = self.nodeinfo["storage"]["name"]
        settings = self.nodeinfo["storage"]["settings"]
        return self._storage_info_from_name(name, settings)

    @property
    def storage(self):
        return self._storage_info()["storage"]

    def _determine_storage(self):
        from .main import fatal
        old_storage_info = self.nodeinfo.get("storage", {})
        old_name = old_storage_info.get("name")
        if self.args.storage:
            name, sep, setting_str = self.args.storage.partition(':')
            settings = {}
            if setting_str:
                for item in setting_str.split(','):
                    key, value = item.split('=', 1)
                    settings[key] = value
            storage_info = self._storage_info_from_name(name, settings)
            if old_name is not None and storage_info["name"] != old_name:
                fatal("cannot change storage type after initialization")
        else:
            if old_name is None:
                name = "sqlite"
            else:
                name = old_name
            settings = old_storage_info.get("settings")
            storage_info = self._storage_info_from_name(name, settings)
        self.nodeinfo["storage"] = dict(
            name=storage_info['name'],
            settings=settings)

    @cached_property
    def secret(self):
        if not self.secretfile.check():
            self.secretfile.dirpath().ensure(dir=1)
            self.secretfile.write(base64.b64encode(os.urandom(32)))
            s = py.std.stat
            self.secretfile.chmod(s.S_IRUSR|s.S_IWUSR)
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
