# PYTHON_ARGCOMPLETE_OK
import os
import sys
import py
import argparse
import shlex
import subprocess
import textwrap
from base64 import b64encode
from contextlib import closing
from devpi import hookspecs
from devpi_common.types import lazydecorator, cached_property
from devpi_common.url import URL
from devpi.use import PersistentCurrent
from devpi_common.request import new_requests_session
from devpi import __version__ as client_version
from pluggy import HookimplMarker
from pluggy import PluginManager
import json
subcommand = lazydecorator()

main_description = """
The devpi commands (installed via devpi-client) wrap common Python
packaging, uploading, installation and testing activities, using a remote
devpi-server managed index.  For more information see http://doc.devpi.net
"""

hookimpl = HookimplMarker("devpiclient")


def main(argv=None):
    if argv is None:
        argv = list(sys.argv)
    hub, method = initmain(argv)
    with closing(hub):
        return method(hub, hub.args)


def initmain(argv):
    pm = get_pluginmanager()
    args = parse_args(argv, pm)
    mod = args.mainloc
    func = "main"
    if ":" in mod:
        mod, func = mod.split(":")
    mod = __import__(mod, None, None, ["__doc__"])
    return Hub(args, pm=pm), getattr(mod, func)


def get_pluginmanager(load_entry_points=True):
    pm = PluginManager("devpiclient")
    # support old plugins, but emit deprecation warnings
    pm._implprefix = "devpiclient_"
    pm.add_hookspecs(hookspecs)
    if load_entry_points:
        pm.load_setuptools_entrypoints("devpi_client")
    pm.check_pending()
    return pm


notset = object()


class Hub:
    class Popen(subprocess.Popen):
        STDOUT = subprocess.STDOUT
        PIPE = subprocess.PIPE
        def __init__(self, cmds, *args, **kwargs):
            cmds = [str(x) for x in cmds]
            subprocess.Popen.__init__(self, cmds, *args, **kwargs)

    def __init__(self, args, file=None, pm=None):
        self._tw = py.io.TerminalWriter(file=file)
        self.args = args
        self.cwd = py.path.local()
        self.quiet = False
        self._last_http_stati = []
        self.http = new_requests_session(agent=("client", client_version))
        if pm is None:
            self.pm = get_pluginmanager()
        else:
            self.pm = pm

    @property
    def hook(self):
        return self.pm.hook

    def close(self):
        self.http.close()

    @property
    def _last_http_status(self):
        return self._last_http_stati[-1]

    def set_quiet(self):
        self.quiet = True

    @property
    def clientdir(self):
        return py.path.local(self.args.clientdir)

    def require_valid_current_with_index(self):
        current = self.current
        if not current.index:
            self.fatal("not connected to an index, see 'devpi use'")
        return current

    # remote http hooks

    def http_api(self, method, url, kvdict=None, quiet=False,
                 auth=notset, basic_auth=notset, cert=notset,
                 check_version=True, fatal=True, type=None,
                 verify=None, headers=None):
        """ send a json request and return a HTTPReply object which
        adds some extra methods to the requests's Reply object.

        This method will bail out if we could not connect or
        the response code is >= 400.

        This method will not output any information to the user
        if ``quiet`` is set to true.

        If type is specified and the json result type does not match,
        bail out fatally (unless fatal = False)
        """
        assert kvdict is None or isinstance(kvdict, (dict, list))
        if isinstance(url, URL):
            url = url.url
        jsontype = "application/json"
        if headers is None:
            headers = {}
        headers["Accept"] = jsontype
        headers["content-type"] = jsontype
        try:
            data = json.dumps(kvdict) if kvdict is not None else None
            if auth is notset:
                auth = self.current.get_auth()
            set_devpi_auth_header(headers, auth)
            if basic_auth is notset:
                basic_auth = self.current.get_basic_auth(url=url)
            if cert is notset:
                cert = self.current.get_client_cert(url=url)
            r = self.http.request(method, url, data=data, headers=headers,
                                  auth=basic_auth, cert=cert, verify=verify)
        except self.http.SSLError as e:
            # If verify was set, re-raise this so it can be handled and retried as appropriate
            self._last_http_stati.append(-1)
            if verify is not None:
                raise
            else:
                self.fatal("SSL verification failed %r:\n%s" % (url, e))
        except self.http.Errors as e:
            self._last_http_stati.append(-1)
            self.fatal("could not connect to %r:\n%s" % (url, e))
        else:
            self._last_http_stati.append(r.status_code)

        if r.url != url:
            self.info("*redirected: %s" %(r.url,))

        reply = HTTPReply(r)

        # if we get a 401 with a location, we assume our login data is expired
        if r.status_code == 401 and "location" in reply.headers:
            if self.current.del_auth():
                self.error("removed expired authentication information")

        if check_version:
            verify_reply_version(self, reply)

        if r.status_code in (200, 201):
            # don't show any extra info on success code
            if type is not None:
                if reply.type != type:
                    self.fatal("%s: got result type %r, expected %r" %(
                                url, reply.type, type))
            return reply
        # feedback reply info to user, possibly bailing out
        if r.status_code >= 400:
            if fatal:
                out = self.fatal
            else:
                out = self.error
        elif quiet and not self.args.debug:
            return reply
        else:
            out = self.info

        if r.status_code >= 400 or self.args.debug:
            info = "%s %s\n" % (r.request.method, r.url)
        else:
            info = ""
        message = reply.json_get("message", getattr(r, 'text', ''))
        if message:
            message = ": " + message
        out("%s%s %s%s" %(info, r.status_code, r.reason, message))
        return reply

    def requires_login(self):
        if not self.current.get_auth_user():
            self.fatal("you need to be logged in (use 'devpi login USER')")

    def raw_input(self, msg):
        try:
            return raw_input(msg)
        except NameError:
            return input(msg)

    def getdir(self, name):
        return self._workdir.mkdir(name)

    @property
    def _workdir(self):
        try:
            return self.__workdir
        except AttributeError:
            self.__workdir = py.path.local.make_numbered_dir(prefix="devpi")
            self.info("using workdir", self.__workdir)
            return self.__workdir

    @cached_property
    def current(self):
        self.clientdir.ensure(dir=1)
        path = self.clientdir.join("current.json")
        return PersistentCurrent(path)

    def get_existing_file(self, arg):
        p = py.path.local(arg, expanduser=True)
        if not p.exists():
            self.fatal("file does not exist: %s" % p)
        elif not p.isfile():
            self.fatal("is not a file: %s" % p)
        return p

    @property
    def venv(self):
        venvdir = None
        vbin = "Scripts" if sys.platform == "win32" else "bin"

        if self.args.venv == "-":
            self.current.reconfigure(dict(venvdir=None))
        else:
            if self.args.venv:
                venvname = self.args.venv
                cand = self.cwd.join(venvname, vbin, abs=True)
                if not cand.check() and self.venvwrapper_home:
                    cand = self.venvwrapper_home.join(venvname, vbin, abs=True)
                if not cand.check():
                    self.create_virtualenv(venvname)
                venvdir = cand.dirpath().strpath
                self.current.reconfigure(dict(venvdir=venvdir))
            else:
                venvdir = self.current.venvdir or self.active_venv()

        return venvdir

    @property
    def venvwrapper_home(self):
        path = os.environ.get("WORKON_HOME", None)
        if path is None:
            return
        return py.path.local(path)

    def active_venv(self):
        """current activated virtualenv"""
        path = os.environ.get("VIRTUAL_ENV", None)
        if path is None:
            return
        return py.path.local(path)

    def create_virtualenv(self, venv):
        if self.venvwrapper_home:
            self.popen_check(["mkvirtualenv", venv])
        else:
            self.popen_check(["virtualenv", "-q", venv])

    def popen_output(self, args, cwd=None, report=True):
        if isinstance(args, str):
            args = shlex.split(args)
        assert args[0], args
        args = [str(x) for x in args]
        if cwd is None:
            cwd = self.cwd
        cmd = py.path.local.sysfind(args[0])
        if not cmd:
            self.fatal("command not found: %s" % args[0])
        args[0] = str(cmd)
        if report:
            self.report_popen(args, cwd)
        return subprocess.check_output(args, cwd=str(cwd)).decode('utf-8')

    def popen(self, args, cwd=None, dryrun=None, **popen_kwargs):
        if isinstance(args, str):
            args = shlex.split(args)
        assert args[0], args
        args = [str(x) for x in args]
        if cwd is None:
            cwd = self.cwd
        self.report_popen(args, cwd)
        if dryrun is None:
            dryrun = self.args.dryrun
        if dryrun:
            return
        popen = subprocess.Popen(args, cwd=str(cwd), **popen_kwargs)
        out, err = popen.communicate()
        ret = popen.wait()
        if ret:
            self.fatal("****** process returned %s" % ret)
        return (ret, out, err)

    def report_popen(self, args, cwd=None, extraenv=None):
        base = cwd or self.cwd
        rel = py.path.local(args[0]).relto(base)
        if not rel:
            rel = str(args[0])
        if extraenv is not None:
            envadd = " [%s]" % ",".join(
                ["%s=%s" % item for item in sorted(extraenv.items())])
        else:
            envadd = ""
        self.line("--> ", base + "$", rel, " ".join(args[1:]), envadd)

    def popen_check(self, args, extraenv=None):
        assert args[0], args
        args = [str(x) for x in args]
        self.report_popen(args, extraenv=extraenv)
        env = os.environ.copy()
        if extraenv is not None:
            env.update(extraenv)
        ret = subprocess.call(args, env=env)
        if ret != 0:
            self.fatal("command failed")

    def line(self, *msgs, **kwargs):
        msg = " ".join(map(str, msgs))
        self._tw.line(msg, **kwargs)

    def ask_confirm(self, msg):
        got = None
        choices = ("yes", "no")
        choicestr = "/".join(choices)
        question = "%s (%s)? " % (msg, choicestr)
        if self.args.yes:
            self.info(question + "yes (autoset from -y option)")
            return True
        while got not in choices:
            got = self.raw_input(question)
            if got in choices:
                break
            self.error("not a valid choice %r" % got)
        return got == "yes"

    # semantic logging
    def debug(self, *msg):
        if self.args.debug and not self.quiet:
            self.line("[debug]", *msg)

    def error(self, *msg):
        if not self.quiet:
            self.line(*msg, red=True)

    def fatal(self, *msg):
        msg = " ".join(map(str, msg))
        self._tw.line(msg, red=True)
        raise SystemExit(1)

    def info(self, *msg):
        if not self.quiet:
            self.line(*msg, bold=True)

    def warn(self, *msg):
        if not self.quiet:
            self.line(*msg, yellow=True, bold=True)

    def out_json(self, data):
        self._tw.line(json.dumps(data, sort_keys=True, indent=4))


class HTTPReply(object):
    def __init__(self, response):
        self._response = response

    def __getattr__(self, name):
        return getattr(self._response, name)

    @property
    def reason(self):
        return self._response.reason

    @property
    def type(self):
        return self._json.get("type")

    @property
    def result(self):
        return self._json.get("result")

    def json_get(self, jsonkey, default=None):
        r = self._response
        if not r.content or r.headers["content-type"] != "application/json":
            return default
        try:
            return self._json[jsonkey]
        except KeyError:
            return default

    @cached_property
    def _json(self):
        try:
            return self._response.json()
        except ValueError:
            return {}

    def __getitem__(self, name):
        return self._json[name]


def set_devpi_auth_header(headers, auth):
    if auth:
        auth = "%s:%s" % auth
        auth = b64encode(auth.encode("ascii")).decode("ascii")
        headers["X-Devpi-Auth"] = auth


class MyArgumentParser(argparse.ArgumentParser):
    class ArgumentError(Exception):
        """ and error from the argparse subsystem. """
    def error(self, error):
        """raise errors instead of printing and raising SystemExit"""
        raise self.ArgumentError(error)


def try_argcomplete(parser):
    if os.environ.get('_ARGCOMPLETE'):
        try:
            import argcomplete
        except ImportError:
            pass
        else:
            argcomplete.autocomplete(parser)


def print_version(hub):
    hub.line("devpi-client %s\n" % client_version)
    if hub.current.rooturl is not None:
        url = URL(hub.current.rooturl).addpath('+status').url
        try:
            r = HTTPReply(hub.http.get(
                url, headers=dict(accept='application/json')))
        except hub.http.Errors:
            pass
        else:
            status = r.json_get('result')
            if r.status_code == 200 and status is not None:
                hub.info(
                    "current devpi server: %s" % hub.current.rooturl)
                versioninfo = status.get('versioninfo', {})
                for name, version in sorted(versioninfo.items()):
                    hub.line("    %s %s" % (name, version))


def parse_args(argv, pm):
    argv = [str(x) for x in argv]
    parser = getbaseparser('devpi')
    add_subparsers(parser, pm)
    try_argcomplete(parser)
    try:
        args = parser.parse_args(argv[1:])
        if sys.version_info >= (3,) and args.version:
            with closing(Hub(args)) as hub:
                print_version(hub)
            parser.exit()
        if args.command is None:
            raise parser.ArgumentError(
                "the following arguments are required: command")
        return args
    except parser.ArgumentError as e:
        if not argv[1:]:
            return parser.parse_args(["-h"])
        parser.print_usage()
        parser.exit(2, "%s: error: %s\n" % (parser.prog, e.args[0]))


def parse_docstring(txt):
    description = txt
    i = txt.find(".")
    if i == -1:
        doc = txt
    else:
        doc = txt[:i+1]
    return doc, description


@hookimpl
def devpiclient_subcommands():
    subcommands = []
    for add_arguments, args, kwargs in subcommand.discover(globals()):
        if len(args) > 1:
            name = args[1]
        else:
            name = add_arguments.__name__
        mainloc = args[0]
        subcommands.append((add_arguments, name, mainloc))
    return subcommands


def add_subparsers(parser, pm):
    subparsers = parser.add_subparsers()
    # see http://stackoverflow.com/questions/18282403/
    # for the following two lines (py3 compat)
    subparsers.required = False
    subparsers.dest = "command"

    subcommands = sum(pm.hook.devpiclient_subcommands(), [])
    for (add_arguments, name, mainloc) in subcommands:
        doc, description = parse_docstring(add_arguments.__doc__)
        subparser = subparsers.add_parser(name,
                                          description=description,
                                          help=doc)
        subparser.Action = argparse.Action
        add_generic_options(subparser)
        add_arguments(subparser)
        subparser.set_defaults(mainloc=mainloc)


def getbaseparser(prog):
    parser = MyArgumentParser(prog=prog, description=main_description)
    if sys.version_info < (3,):
        # workaround old argparse which doesn't support optional sub commands
        parser.add_argument("--version", action="version",
            version="devpi-client %s" % client_version)
    else:
        parser.add_argument("--version", action="store_true",
            help="show program's version number and exit")
    add_generic_options(parser, defaults=True)
    return parser


def add_generic_options(parser, defaults=False):
    group = parser.add_argument_group("generic options")
    group.add_argument("--debug", action="store_true",
        help="show debug messages including more info on server requests")
    group.add_argument("-y", action="store_true", dest="yes",
        help="assume 'yes' on confirmation questions")
    group.add_argument("-v", "--verbose", action="count",
        help="increase verbosity")
    # workaround for http://bugs.python.org/issue23058
    if defaults:
        clientdir_default = os.path.expanduser(
            os.environ.get("DEVPI_CLIENTDIR", "~/.devpi/client"))
    else:
        # subcommands will have their default being suppressed, so only the
        # main one is used
        clientdir_default = argparse.SUPPRESS
    group.add_argument("--clientdir", action="store", metavar="DIR",
        default=clientdir_default,
        help="directory for storing login and other state")


@subcommand("devpi.use")
def use(parser):
    """ show/configure current index and target venv for install
    activities.

    This shows client-side state, relevant for server interactions,
    including login authentication information, the current remote index
    (and API endpoints if you specify --urls) and the target virtualenv
    for installation activities.
    """

    parser.add_argument("--set-cfg", action="store_true", default=None,
        dest="setcfg",
        help="create or modify pip/setuptools config files so "
             "pip/easy_install will pick up the current devpi index url. "
             "If a virtualenv is activated, only its pip config will be set.")
    parser.add_argument("-t", "--pip-set-trusted", choices=["yes", "no", "auto"], default="auto",
        dest="settrusted",
        help="when used in conjunction with set-cfg, also set matching "
             "pip trusted-host setting for the provided devpi index url. "
             "With 'auto', trusted will be set for http urls or hosts that "
             "fail https ssl validation. 'no' will clear setting")
    parser.add_argument("--always-set-cfg",
        choices=["yes", "no"], default=None,
        dest="always_setcfg",
        help="on 'yes', all subsequent 'devpi use' will implicitely use "
             "--set-cfg.  The setting is stored with the devpi client "
             "config file and can be cleared with '--always-set-cfg=no'.")
    parser.add_argument("--venv", action="store", default=None,
        help="set virtual environment to use for install activities. "
             "specify '-' to unset it. "
             "venv be created if given name doesn't already exist. "
             "Note: an activated virtualenv will be used without needing this.")
    parser.add_argument("--urls", action="store_true",
        help="show remote endpoint urls")
    parser.add_argument("-l", action="store_true", dest="list",
        help="show all available indexes at the remote server")
    parser.add_argument("--delete", action="store_true",
        help="delete current association with server")
    parser.add_argument("--client-cert", action="store", default=None,
        metavar="pem_file",
        help="use the given .pem file as the SSL client certificate to "
             "authenticate to the server (EXPERIMENTAL)")
    parser.add_argument("url", nargs="?",
        help="set current API endpoints to the ones obtained from the "
             "given url.  If already connected to a server, you can "
             "specify '/USER/INDEXNAME' which will use the same server "
             "context. If you specify the root url you will not be connected "
             "to a particular index. If you have a web server with basic auth "
             "in front of devpi-server, then use a url like this: "
             "https://username:password@example.com/USER/INDEXNAME")


@subcommand("devpi.getjson")
def getjson(parser):
    """ show remote server and index configuration.

    A low-level command to show json-formatted configuration data
    from remote resources.  This will always query the remote server.
    """
    parser.add_argument("path", action="store", metavar="path_or_url",
        help="path or url of a resource to show information on. "
             "examples: '/', '/user', '/user/index'.")


@subcommand("devpi.getjson:main_patchjson")
def patchjson(parser):
    """ send a PATCH request with the specified json content to
    the specified path.

    A low-level command to patch json requests at remote resources.
    """
    parser.add_argument("path", action="store",
        help="path to a resource to patch information on. ")
    parser.add_argument("jsonfile", action="store",
        help="file to read json content from")


@subcommand("devpi.list_remove:main_list", "list")
def list_(parser):
    """ list project versions and files for the current index.

    Without a spec argument this command will show the names
    of all projects which have releases on the current index.
    You can use a pip/setuptools style spec argument to show files
    for particular versions of a project.
    RED files come from an an inherited version which is
    shadowed by an inheriting index.
    """
    parser.add_argument("-f", "--failures", action="store_true",
        dest="failures",
        help="show test setup/failure logs (implies -t)")

    parser.add_argument("--all", action="store_true",
        help="show all versions instead of just the newest")

    parser.add_argument("-t", "--toxresults", action="store_true",
        help="show toxresults for the releases")

    parser.add_argument("--index", default=None,
        help="index to look at (defaults to current index)")

    parser.add_argument(
        "--ignore-bases", action="store_true", default=False,
        help="ignore releases from inherited bases. "
             "Requires devpi-server >= 5.0.0.")

    parser.add_argument("spec", nargs="?",
        help="show info for a project or a specific release. "
             "Example specs: pytest or 'pytest>=2.3.5'"
             " (Quotes are needed to prevent shell redirection)")


@subcommand("devpi.list_remove:main_remove")
def remove(parser):
    """\
    removes project info/files from current index.

    This command allows to remove projects or releases from your current index
    (see "devpi use").
    It will ask interactively for confirmation before performing the actual removals.
    """
    parser.add_argument("--index", default=None,
        help="index to remove from (defaults to current index)")
    parser.add_argument("-f", "--force", action="store_true", default=False,
        help="remove even on non-volatile index (with devpi-server >= 6.0.0)")
    parser.add_argument("spec_or_url",
        help="""\
        describes project/version/release file(s) to release from the current index.
        If the spec starts with 'http://' or 'https://',
        it is considered as a request to delete a single file.""")
    parser.formatter_class = argparse.RawDescriptionHelpFormatter
    parser.description = textwrap.dedent(remove.__doc__)
    parser.epilog = textwrap.dedent("""\
        examples:
          devpi remove pytest

          devpi remove pytest>=2.3.5

          devpi remove https://mydevpi.org/dev/+f/1cf/3d6eaa6cbc5fa/pytest-1.0.zip""")


@subcommand("devpi.user")
def user(parser):
    """ add, remove, modify, list user configuration.

    This is the central command for performing remote user
    configuration and manipulation.  Each indexes (created in turn
    by "devpi index" command) is owned by a particular user.
    If you create a user you either need to pass a ``password=...``
    setting or interactively type a password.
    """
    group = parser.add_mutually_exclusive_group()
    group.add_argument("-c", "--create", action="store_true",
        help="create a user")
    group.add_argument("--delete", action="store_true",
        help="delete a user")
    group.add_argument("-m", "--modify", action="store_true",
        help="modify user settings")
    group.add_argument("-l", "--list", action="store_true",
        help="list user names")
    parser.add_argument("username", type=str, action="store", nargs="?",
        help="user name")
    parser.add_argument("keyvalues", nargs="*", type=str,
        help="key=value configuration item.  Possible keys: "
             "email, password and pwhash.")


@subcommand("devpi.user:passwd")
def passwd(parser):
    """ change password of specified user or current user if not specified. """
    parser.add_argument(
        "username", type=str, action="store", nargs="?", help="user name")


@subcommand("devpi.login")
def login(parser):
    """ login to devpi-server with the specified user.

    This command performs the login protocol with the remove server
    which typically results in a cached auth token which is valid for
    ten hours.  You can check your login information with "devpi use".
    """
    parser.add_argument("--password", action="store", default=None,
                        help="password to use for login (prompt if not set)")
    parser.add_argument("username", action="store", default=None,
                        help="username to use for login")


@subcommand("devpi.login:logoff")
def logoff(parser):
    """ log out of the current devpi-server.

    This will erase the client-side login token (see "devpi login").
    """


@subcommand("devpi.login:logoff")
def logout(parser):
    """ log out of the current devpi-server.

    This will erase the client-side login token (see "devpi login").
    """


@subcommand("devpi.index")
def index(parser):
    """ create, delete and manage indexes.

    This is the central command to create and manipulate indexes.
    The index is always created under the currently logged in user
    with a command like this: ``devpi index -c newindex``.

    You can also view the configuration of any index with
    ``devpi index USER/INDEX`` or list all indexes of the
    in-use index with ``devpi index -l``.

    For the ``keyvalues`` option CSV means "Comma Separated Value", in other
    words, a list of values separated by commas.
    """
    group = parser.add_mutually_exclusive_group()
    group.add_argument("-c", "--create", action="store_true",
        help="create an index")
    group.add_argument("--delete", action="store_true",
        help="delete an index")
    group.add_argument("-l", "--list", action="store_true",
        help="list indexes for the logged in user")
    group.add_argument(
        "--no-projects", action="store_true",
        help="when showing the index data, don't include projects")
    parser.add_argument("indexname", type=str, action="store", nargs="?",
        help="index name, specified as NAME or USER/NAME.  If no index "
             "is specified use the current index")
    parser.add_argument("keyvalues", nargs="*", type=str,
        help="key=value configuration item. Possible key=value are "
             "bases=CSV, volatile=True|False, acl_upload=CSV)")


@subcommand("devpi.upload")
def upload(parser):
    """ (build and) upload packages to the current devpi-server index.

    You can directly upload existing release files by specifying
    their file system path as positional arguments.  Such release files
    need to contain package metadata as created by setup.py or
    wheel invocations.

    Or, if you don't specify any path, a setup.py file must exist
    and will be used to perform build and upload commands.

    If you have a ``setup.cfg`` file you can have a "[devpi:upload]" section
    with ``formats``, ``no-vcs = 1``, and ``setupdir-only = 1`` settings
    providing defaults for the respective command line options.
    """
    #parser.add_argument("--ver", dest="setversion",
    #    action="store", default=None,
    #    help="fill version string into setup.py, */__init__.py */conf.py files")
    #parser.add_argument("--incver", action="store_true",
    #    help="retrieve max remove version, increment and set it like --ver")
    build = parser.add_argument_group("build options")

    build.add_argument(
        "-p", "--python", default=None, metavar="PYTHON_EXE",
        help="Specify which Python interpreter to use.")
    build.add_argument("--no-vcs", action="store_true", dest="novcs",
        help="don't VCS-export to a fresh dir, just execute setup.py scripts "
             "directly using their dirname as current dir. By default "
             "git/hg/svn/bazaar are auto-detected and packaging is run from "
             "a fresh directory with all versioned files exported.")
    build.add_argument("--setupdir-only", action="store_true",
        dest="setupdironly",
        help="VCS-export only the directory containing setup.py")

    build.add_argument("--formats", default="", action="store",
        help="comma separated list of build formats (passed to setup.py). "
             "Examples sdist.zip,bdist_egg,bdist_wheel,bdist_dumb.")
    build.add_argument("--with-docs", action="store_true", default=None,
        dest="withdocs",
        help="build sphinx docs and upload them to index. "
             "this triggers 'setup.py build_sphinx' for building")
    build.add_argument("--only-docs", action="store_true", default=None,
        dest="onlydocs",
        help="as --with-docs but don't build or upload release files")

    direct = parser.add_argument_group("direct file upload options")
    direct.add_argument("--index", default=None,
        help="index to upload to (defaults to current index)")
    direct.add_argument("--from-dir", action="store_true", default=None,
        dest="fromdir",
        help="recursively look for archive files in path if it is a dir")
    direct.add_argument("--only-latest", action="store_true",
        help="upload only latest version if multiple archives for a "
             "package are found (only effective with --from-dir)")
    direct.add_argument("--dry-run", dest="dryrun",
        action="store_true", default=None,
        help="don't perform any server-modifying actions")
    direct.add_argument("path", action="store", nargs="*",
        help="path to archive file to be inspected and uploaded.")
    #parser.add_argument("-y", dest="yes",
    #    action="store_true", default=None,
    #    help="answer yes on interactive questions. ")
    #


@subcommand("devpi.test")
def test(parser):
    """ download and test a package against tox environments.

    Download a package and run tests as configured by the
    tox.ini file (which must be contained in the package).
    """
    parser.add_argument("-e", metavar="ENVNAME", type=str, dest="venv",
        default=None, action="store",
        help="tox test environment to run from the tox.ini")

    parser.add_argument("-c", metavar="PATH", type=str, dest="toxini",
        default=None, action="store",
        help="tox configuration file to use with unpacked package")

    parser.add_argument("--fallback-ini", metavar="PATH", type=str,
        dest="fallback_ini",
        default=None, action="store",
        help="tox ini file to be used if the downloaded package has none")

    parser.add_argument("--tox-args", metavar="toxargs", action="store",
        dest="toxargs", default=None,
        help="extra command line arguments for tox. e.g. "
             "--toxargs=\"-c othertox.ini\"")

    parser.add_argument("--detox", "-d", action="store_true",
        dest="detox", default=False,
        help="(experimental) run tests concurrently in multiple processes using "
             "the detox tool (which must be installed)")

    parser.add_argument("--no-upload", action="store_false",
        dest="upload_tox_results", default=True,
        help="Skip upload of tox results")

    parser.add_argument("--index", default=None,
        help="index to get package from, defaults to current index. "
             "Either just the NAME, using the current user, USER/NAME using "
             "the current server or a full URL for another server.")

    parser.add_argument(
        "--select", "-s", metavar="SELECTOR",
        type=str, default=None, action="store",
        help="Selector for release files. "
             "This is a regular expression to select release files for which "
             "tests will be run. With this option it's possible to select "
             "wheels that aren't universal, or run tests only for one "
             "specific release file.")

    parser.add_argument(
        "--list", "-l", action="store_true",
        help="Just list the release files which would be tested.")

    parser.add_argument("pkgspec", metavar="pkgspec", type=str,
        default=None, action="store", nargs="+",
        help="package specification in pip/setuptools requirement-syntax, "
             "e.g. 'pytest' or 'pytest==2.4.2'")


@subcommand("devpi.push")
def push(parser):
    """ push a release and releasefiles to an internal or external index.

        You can push a release with all its release files either
        to an external pypi server ("pypi:REPONAME") where REPONAME
        needs to be defined in your ``.pypirc`` file.  Or you can
        push to another devpi index ("user/name").
    """
    parser.add_argument("--index", default=None,
        help="index to push from (defaults to current index)")
    parser.add_argument("--pypirc", metavar="path", type=str,
        default=None, action="store",
        help="path to pypirc")
    parser.add_argument("pkgspec", metavar="pkgspec", type=str,
        default=None, action="store",
        help="release in format 'name==version'. of which the metadata and "
             "all release files are to be uploaded to the specified "
             "external pypi repo.")
    parser.add_argument("target", metavar="TARGETSPEC", type=str,
        action="store",
        help="local or remote target index. local targets are of form "
             "'USER/NAME', specifying an existing writeable local index. "
             "remote targets are of form 'REPO:' where REPO must be an "
             "existing entry in the pypirc file.")


@subcommand("devpi.install")
def install(parser):
    """ install packages through current devpi index.

    This is convenience wrapper which configures and invokes
    ``pip install`` commands for you, using the current index.
    """
    parser.add_argument("--index", default=None,
        help="index to get package from (defaults to current index)")
    parser.add_argument("-l", action="store_true", dest="listinstalled",
        help="print list of currently installed packages. ")
    parser.add_argument("-e", action="store", dest="editable", metavar="ARG",
        help="install a project in editable mode. ")
    parser.add_argument("--venv", action="store", metavar="DIR",
        help="install into specified virtualenv (created on the fly "
             "if none exists).")
    parser.add_argument("-r", "--requirement", action="store_true",
        help="Install from the given requirements file.")
    parser.add_argument("pkgspecs", metavar="pkg", type=str,
        action="store", default=None, nargs="*",
        help="uri or package file for installation from current index. """)


@subcommand("devpi.refresh")
def refresh(parser):
    """ invalidates the mirror caches for the specified package(s).

    In case your devpi server hasn't updated the list of latest releases, this
    forces a reload of the them (EXPERIMENTAL).
    """
    parser.add_argument("--index", default=None,
        help="index to refresh (defaults to current index)")
    parser.add_argument(
        "pkgnames", metavar="pkg", type=str, action="store", nargs="+",
        help="package name to refresh.""")


def verify_reply_version(hub, reply):
    acceptable_api_version = ("2",)
    version = reply.headers.get("X-DEVPI-API-VERSION", None)
    if version is None:
        if not hasattr(hub, "_WARNAPI_DELIVERED"):
            hub.error("WARN: devpi-client-%s got an unversioned reply, "
                      "assuming API-VERSION 2 (as implemented by "
                      "devpi-server-2.0)" % client_version)
            hub._WARNAPI_DELIVERED = True
        return
    if version in acceptable_api_version:
        return
    hub.fatal("devpi-client-%s got a reply with API-VERSION %s, "
              "acceptable are: %s" %(client_version, version,
                                     ",".join(acceptable_api_version)))
