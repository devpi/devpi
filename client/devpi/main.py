# PYTHON_ARGCOMPLETE_OK
import os
import sys
import py
import argparse
import subprocess
from devpi.util.lazydecorator import lazydecorator
from devpi.util import url as urlutil
from devpi import log, cached_property
from devpi.use import Current
import devpi.server
import requests
import json
from devpi.server import handle_autoserver
std = py.std
subcommand = lazydecorator()

from devpi import __version__

main_description = """
The devpi sub commands (installed via devpi-client) wrap common Python
packaging, uploading, installation and testing activities, using a remote
devpi-server managed index.  If using the default http://localhost:3141 server
location, devpi-client will automatically start a server in the background
if no server is responding on that address.  This behaviour is controlled
by the ``devpi server`` subcommand which also provides access to log files.
For more information see http://doc.devpi.net

"""

def main(argv=None):
    if argv is None:
        argv = list(sys.argv)
    hub, method = initmain(argv)
    return method(hub, hub.args)

def initmain(argv):
    args = parse_args(argv)
    mod = args.mainloc
    func = "main"
    if ":" in mod:
        mod, func = mod.split(":")
    mod = __import__(mod, None, None, ["__doc__"])
    return Hub(args), getattr(mod, func)

def check_output(*args, **kwargs):
    from subprocess import Popen, CalledProcessError, PIPE
    # subprocess.check_output does not exist on python26
    popen = Popen(stdout=PIPE, *args, **kwargs)
    output, unused_err = popen.communicate()
    retcode = popen.poll()
    if retcode:
        cmd = kwargs.get("args")
        if cmd is None:
            cmd = args[0]
        if sys.version_info < (2,7) and sys.platform == "win32":
            raise CalledProcessError(retcode, cmd)
        else:
            raise CalledProcessError(retcode, cmd, output=output)
    return output

class Hub:
    class Popen(std.subprocess.Popen):
        STDOUT = std.subprocess.STDOUT
        PIPE = std.subprocess.PIPE
        def __init__(self, cmds, *args, **kwargs):
            cmds = [str(x) for x in cmds]
            std.subprocess.Popen.__init__(self, cmds, *args, **kwargs)

    def __init__(self, args, file=None):
        self._tw = py.io.TerminalWriter(file=file)
        self.args = args
        self.cwd = py.path.local()
        self.quiet = False
        self._last_http_status = None
        self._session = requests.session()

    def set_quiet(self):
        self.quiet = True

    @property
    def clientdir(self):
        return py.path.local(self.args.clientdir)

    def require_valid_current_with_index(self):
        if not self.current.simpleindex:
            handle_autoserver(self, self.current)
        return self.current

    # remote http hooks

    @property
    def http(self):
        session = self._session
        #session.auth = tuple(self.current.auth) if self.current.auth else None
        session.ConnectionError = requests.exceptions.ConnectionError
        return session

    def http_api(self, method, url, kvdict=None, quiet=False):
        """ send a json request and return a HTTPReply object which
        adds some extra methods to the requests's Reply object.

        This method will bail out if we could not connect or
        the response code is >= 400.

        This method will not output any information to the user
        if ``quiet`` is set to true.
        """
        jsontype = "application/json"
        headers = {"Accept": jsontype, "content-type": jsontype}
        try:
            data = json.dumps(kvdict) if kvdict is not None else None
            auth = tuple(self.current.auth) if self.current.auth else None
            r = self.http.request(method, url, data=data, headers=headers,
                                  auth=auth)
        except self.http.ConnectionError:
            self._last_http_status = -1
            self.fatal("could not connect to %r" % (url,))
        self._last_http_status = r.status_code

        reply = HTTPReply(r)

        # if we get a 401 it means our auth info is expired or not present
        if r.status_code == 401:
            if self.delete_auth():
                self.error("removed expired authentication information")

        if r.status_code in (200, 201):
            # don't show any extra info on success code
            return reply
        # feedback reply info to user, possibly bailing out
        if r.status_code >= 400:
            out = self.fatal
        elif quiet and not self.args.debug:
            return reply
        else:
            out = self.info

        if r.status_code >= 400 or self.args.debug:
            info = "%s %s\n" % (r.request.method, r.url)
        else:
            info = ""
        message = reply.json_get("message", "")
        if message:
            message = ": " + message
        out("%s%s %s%s" %(info, r.status_code, r.reason, message))
        return reply



    def delete_auth(self):
        loginpath = self.clientdir.join("login")
        if loginpath.check():
            loginpath.remove()
            return True

    def requires_login(self):
        if not self.current.auth:
            self.fatal("you need to be logged in (use 'devpi login USER')")

    def get_index_url(self, indexname=None, current=None, slash=True):
        if current is None:
            current = self.current
        if indexname is None:
            indexname = current.index
            if indexname is None:
                raise ValueError("no index name")
        if "/" not in indexname:
            assert self.current.auth[0]
            userurl = current.getuserurl(self.current.auth[0])
            return urlutil.joinpath(userurl + "/", indexname)
        url = urlutil.joinpath(current.rooturl, indexname)
        url = url.rstrip("/")
        if slash:
            url = url.rstrip("/") + "/"
        return url

    def get_project_url(self, name):
        baseurl = self.get_index_url(slash=True)
        url = urlutil.joinpath(baseurl, name) + "/"
        return url

    def get_user_url(self):
        return self.current.getuserurl(self.current.auth[0])

    def raw_input(self, msg):
        return raw_input(msg)

    def getdir(self, name):
        return self._workdir.mkdir(name)

    @property
    def _workdir(self):
        try:
            return self.__workdir
        except AttributeError:
            self.__workdir = py.path.local.make_numbered_dir(prefix="devpi")
            self.info("created workdir", self.__workdir)
            return self.__workdir

    @cached_property
    def current(self):
        self.clientdir.ensure(dir=1)
        path = self.clientdir.join("current.json")
        current = Current(path)
        try:
            cmd = self.args.mainloc.split(":")[0]
            if cmd not in ("devpi.use", "devpi.server"):
                handle_autoserver(self, current)
        except AttributeError:
            pass
        return current

    @property
    def remoteindex(self):
        try:
            return self._remoteindex
        except AttributeError:
            from devpi.remoteindex import RemoteIndex
            self._remoteindex = RemoteIndex(self.current)
            return self._remoteindex

    @property
    def path_venvbase(self):
        path = os.environ.get("WORKON_HOME", None)
        if path is None:
            return
        return py.path.local(path)

    def popen_output(self, args, cwd=None):
        if isinstance(args, str):
            args = std.shlex.split(args)
        assert args[0], args
        args = [str(x) for x in args]
        if cwd == None:
            cwd = self.cwd
        self.report_popen(args, cwd)
        if self.args.dryrun:
            return
        return check_output(args, cwd=str(cwd))

    def report_popen(self, args, cwd=None):
        base = cwd or self.cwd
        rel = py.path.local(args[0]).relto(base)
        if not rel:
            rel = str(args[0])
        self.line("--> $", rel, " ".join(args[1:]))

    def popen_check(self, args):
        assert args[0], args
        args = [str(x) for x in args]
        self.report_popen(args)
        ret = subprocess.call(args)
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
            got = raw_input(question)
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

    def out_json(self, data):
        self._tw.line(json.dumps(data, sort_keys=True, indent=4))


class HTTPReply(object):
    def __init__(self, response):
        self._response = response

    def __getattr__(self, name):
        return getattr(self._response, name)

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
        return self._response.json()

    def __getitem__(self, name):
        return self._json[name]


class MyArgumentParser(argparse.ArgumentParser):
    class ArgumentError(Exception):
        """ and error from the argparse subsystem. """
    def error(self, error):
        """raise errors instead of printing and raising SystemExit"""
        raise self.ArgumentError(error)

    #def __init__(self, *args, **kwargs):
    #    kwargs["formatter_class"] = MyHelpFormatter
    #    argparse.ArgumentParser.__init__(self, *args, **kwargs)

#class MyHelpFormatter(argparse.HelpFormatter):
#    pass

def try_argcomplete(parser):
    try:
        import argcomplete
    except ImportError:
        pass
    else:
        argcomplete.autocomplete(parser)

def parse_args(argv):
    argv = map(str, argv)
    parser = getbaseparser(argv[0])
    add_subparsers(parser)
    try_argcomplete(parser)
    try:
        return parser.parse_args(argv[1:])
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

def add_subparsers(parser):
    subparsers = parser.add_subparsers()
    for func, args, kwargs in subcommand.discover(globals()):
        if len(args) > 1:
            name = args[1]
        else:
            name = func.__name__
        doc, description = parse_docstring(func.__doc__)
        subparser = subparsers.add_parser(name,
                                          description=description,
                                          help=doc)
        subparser.Action = argparse.Action
        add_generic_options(subparser)
        func(subparser)
        mainloc = args[0]
        subparser.set_defaults(mainloc=mainloc)
    #subparser = subparsers.add_parser("_test", help=argparse.SUPPRESS)
    #subparser.set_defaults(mainloc="devpi")

def getbaseparser(prog):
    parser = MyArgumentParser(prog=prog, description=main_description)
    add_generic_options(parser)
    return parser

def add_generic_options(parser):
    group = parser.add_argument_group("generic options")
    group.add_argument("--version", action="version",
                       version=devpi.__version__)
    group.add_argument("--debug", action="store_true",
        help="show debug messages including more info on server requests")
    group.add_argument("-y", action="store_true", dest="yes",
        help="assume 'yes' on confirmation questions")
    #group.add_argument("-v", "--verbose", action="store_true",
    #    help="increase verbosity")
    group.add_argument("--clientdir", action="store", metavar="DIR",
        default=os.path.expanduser(os.environ.get("DEVPI_CLIENTDIR",
                                                  "~/.devpi/client")),
        help="directory for storing login and other state")

@subcommand("devpi.use")
def use(parser):
    """ show/configure current index and target venv for install
    activities.

    This shows client-side state, relevant for devpi-server interactions,
    including login authentication information, the current remote index
    (and API endpoints if you specify --urls) and the target virtualenv
    for installation activities.
    """

    parser.add_argument("--venv", action="store", default=None,
        help="set virtual environment to use for install activities. "
             "specify '-' to unset it.")
    parser.add_argument("--no-auto", action="store_true", dest="noauto",
        help="don't start automatic server")
    parser.add_argument("--urls", action="store_true",
        help="show remote endpoint urls")
    parser.add_argument("--delete", action="store_true",
        help="delete current association with server")
    parser.add_argument("url", nargs="?",
        help="set current API endpoints to the ones obtained from the "
             "given url.  If already connected to a server, you can "
             "specify '/USER/INDEXNAME' which will use the same server "
             "context. If you specify the root url you will not be connected "
             "to a particular index. ")

@subcommand("devpi.getjson")
def getjson(parser):
    """ show remote server and index configuration.

    A low-level command to show json-formatted configuration data
    from remote resources.  This will always query the remote server.
    """
    parser.add_argument("path", action="store",
        help="path to a resource to show information on. "
             "examples: '/', '/user', '/user/index'.")

@subcommand("devpi.list_remove:main_list", "list")
def list_(parser):
    """ list project versions and files for the current index.

    Without a ``spec`` argument this command will show the names
    of all projects that have been used.  With a spec argument
    it will show all release files.  RED files come from an
    an inherited version which is shadowed by an inheriting index.
    """
    parser.add_argument("-f", "--failures", action="store_true",
        dest="failures",
        help="show test setup/failure logs")
    parser.add_argument("spec", nargs="?",
        help="show only info for a project/version/release file.  "
             "Example specs: 'pytest' or 'pytest-2.3.5' or "
             "'pytest-2.3.5.tar.gz'")

@subcommand("devpi.list_remove:main_remove")
def remove(parser):
    """ remove project info/files from current index.

    This command allows to remove projects or releases from your
    current index (see "devpi use").  It will ask interactively
    for confirmation before performing the actual removals.
    """
    parser.add_argument("spec",
        help="remove info/files for a project/version/release file from the "
             "current index. "
             "Example specs: 'pytest' or 'pytest-2.3.5' or 'pytest-2.3.5.tar.gz'")

@subcommand("devpi.user")
def user(parser):
    """ add, remove, modify, list user configuration.

    This is the central command for performing remote user
    configuration and manipulation.  Each indexes (created in turn
    by "devpi index" command) is owned by a particular user.
    If you create a user you either need to pass a ``password=...``
    setting or interactively type a password.
    """
    parser.add_argument("-c", "--create", action="store_true",
        help="create a user")
    parser.add_argument("--delete", action="store_true",
        help="delete a user")
    parser.add_argument("-m", "--modify", action="store_true",
        help="modify user settings")
    parser.add_argument("-l", "--list", action="store_true",
        help="list user names")
    parser.add_argument("username", type=str, action="store", nargs="?",
        help="user name")
    parser.add_argument("keyvalues", nargs="*", type=str,
        help="key=value configuration item.  Possible keys: "
             "email, password.")

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

@subcommand("devpi.index")
def index(parser):
    """ create, delete and manage indexes.

    This is the central command to create and manipulate indexes.
    The index is always created under the currently logged in user
    with a command like this: ``devpi index -c newindex``.

    You can also view the configuration of any index with
    ``devpi index USER/INDEX`` or list all indexes of the
    in-use index with ``devpi index -l``.
    """
    group = parser.add_mutually_exclusive_group()
    group.add_argument("-c", "--create", action="store_true",
        help="create an index")
    group.add_argument("--delete", action="store_true",
        help="delete an index")
    group.add_argument("-l", "--list", action="store_true",
        help="list indexes for the logged in user")
    parser.add_argument("indexname", type=str, action="store", nargs="?",
        help="index name, specified as NAME or USER/NAME.  If no index "
             "is specified use the current index")
    parser.add_argument("keyvalues", nargs="*", type=str,
        help="key=value configuration item. Possible key=value are "
             "bases=CSV, volatile=True|False, acl_upload=CSV)")

@subcommand("devpi.upload.upload")
def upload(parser):
    """ prepare and upload packages to the current index.

    This command wraps ``setup.py`` invocations to build and
    upload releases, release files and documentation to your
    in-use index (see "devpi use").
    """
    #parser.add_argument("-l", dest="showstatus",
    #    action="store_true", default=None,
    #    help="show remote versions, local version and package types")
    parser.add_argument("--ver", dest="setversion",
        action="store", default=None,
        help="fill version string into setup.py, */__init__.py */conf.py files")
    #parser.add_argument("--incver", action="store_true",
    #    help="retrieve max remove version, increment and set it like --ver")
    parser.add_argument("--formats", default="sdist.tgz", action="store",
        help="comma separated list of build formats (passed to setup.py). "
             "Examples sdist.zip,bdist_egg,bdist_wheel,bdist_dumb.")
    parser.add_argument("--from-dir", action="store", default=None,
        dest="fromdir",
        help="upload all archive files from the specified directory")
    parser.add_argument("--only-latest", action="store_true",
        help="upload only latest version if multiple archives for a "
             "package are found (only effective with --from-dir)")
    parser.add_argument("--dry-run", dest="dryrun",
        action="store_true", default=None,
        help="don't perform any server-modifying actions")
    parser.add_argument("--with-docs", action="store_true", default=None,
        dest="withdocs",
        help="build sphinx docs and upload them to index. "
             "this triggers 'setup.py build_sphinx ... upload_docs ...'")
    parser.add_argument("--only-docs", action="store_true", default=None,
        dest="onlydocs",
        help="as --with-docs but don't upload release files")
    #parser.add_argument("-y", dest="yes",
    #    action="store_true", default=None,
    #    help="answer yes on interactive questions. ")
    #

@subcommand("devpi.test.test")
def test(parser):
    """ download and test a package against tox environments.

    Download a package and run tests as configured by the
    tox.ini file (which must be contained in the package).
    """
    parser.add_argument("-e", metavar="VENV", type=str, dest="venv",
        default=None, action="store",
        help="virtual environment to run from the tox.ini")

    parser.add_argument("pkgspec", metavar="pkgspec", type=str,
        default=None, action="store", nargs=1,
        help="package specification to download and test")

@subcommand("devpi.push")
def push(parser):
    """ push a release and releasefiles to an external index server.

        You can push a release with all its release files either
        to a remote pypi target ("pypi:REPONAME") or another
        devpi index ("user/name").
    """
    parser.add_argument("--pypirc", metavar="path", type=str,
        default=None, action="store",
        help="path to pypirc")
    parser.add_argument("nameversion", metavar="NAME-VER", type=str,
        default=None, action="store",
        help="release in format 'name-version'. of which the metadata and "
             "all release files are to be uploaded to the specified "
             "external pypi repo." )
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
    parser.add_argument("-l", action="store_true", dest="listinstalled",
        help="print list of currently installed packages. ")
    parser.add_argument("-e", action="store", dest="editable", metavar="ARG",
        help="install a project in editable mode. ")
    parser.add_argument("--venv", action="store", metavar="DIR",
        help="install into specified virtualenv (created on the fly "
             "if none exists).")
    parser.add_argument("pkgspecs", metavar="pkg", type=str,
        action="store", default=None, nargs="*",
        help="uri or package file for installation from current index. """
    )

@subcommand("devpi.server")
def server(parser):
    """ commands for controling the automatic server.

    Check logs and status of the "automatic" server which is invoked
    implicitely with many subcommands if you use the default
    http://localhost:3141/ server address and no server is
    currently running there.
    """
    parser.add_argument("--stop", action="store_true",
        help="stop automatically started server if any")
    parser.add_argument("--log", action="store_true",
        help="show last log lines of automatic server")

if __name__ == "__main__":
    main()
