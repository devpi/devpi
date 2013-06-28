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
        raise CalledProcessError(retcode, cmd, output=output)
    return output

class Hub:
    class Popen(std.subprocess.Popen):
        STDOUT = std.subprocess.STDOUT
        PIPE = std.subprocess.PIPE
        def __init__(self, cmds, *args, **kwargs):
            cmds = [str(x) for x in cmds]
            std.subprocess.Popen.__init__(self, cmds, *args, **kwargs)

    def __init__(self, args):
        self._tw = py.io.TerminalWriter()
        self.args = args
        self.cwd = py.path.local()
        self.quiet = False

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

    @cached_property
    def http(self):
        session = requests.session()
        p = self.clientdir.join("login")
        if p.check():
            data = json.loads(p.read())
            session.auth = data["user"], data["password"]
        session.ConnectionError = requests.exceptions.ConnectionError
        return session

    def http_api(self, method, url, kvdict=None, quiet=False):
        methodexec = getattr(self.http, method, None)
        jsontype = "application/json"
        headers = {"Accept": jsontype, "content-type": jsontype}
        if method in ("delete", "get"):
            r = methodexec(url, headers=headers)
        elif method == "push":
            r = self.http.request(method, url, data=json.dumps(kvdict),
                                  headers=headers)
        else:
            r = methodexec(url, json.dumps(kvdict), headers=headers)
        if r.status_code < 0:
            self.fatal("%s: could not connect to %r" % (r.status_code, url))
        out = self.info
        if r.status_code >= 400:
            out = self.fatal
        elif quiet:
            out = lambda *args, **kwargs: None

        if r.status_code >= 400 or self.args.debug:
            info = "%s %s\n" % (method.upper(), r.url)
        else:
            info = ""
        data = r.content
        if data and r.headers["content-type"] == "application/json":
            data = json.loads(data)
            reason = data.get("message", r.reason)
        else:
            reason = r.reason
        out("%s%s: %s" %(info, r.status_code, reason))
        return data

    def update_auth(self, user, password):
        self.http.auth = (user, password)
        self.clientdir.ensure(dir=1)
        oldumask = os.umask(7*8+7)
        try:
            self.clientdir.join("login").write(
                json.dumps(dict(user=user, password=password)))
        finally:
            os.umask(oldumask)

    def delete_auth(self):
        loginpath = self.clientdir.join("login")
        if loginpath.check():
            loginpath.remove()

    def requires_login(self):
        if not self.http.auth:
            self.fatal("you need to be logged in (use 'devpi login USER')")

    def get_index_url(self, indexname=None, current=None):
        if current is None:
            current = self.current
        if indexname is None:
            indexname = current.index
            if indexname is None:
                raise ValueError("no index name")
        if "/" not in indexname:
            assert self.http.auth[0]
            userurl = current.getuserurl(self.http.auth[0])
            return urlutil.joinpath(userurl + "/", indexname)
        return urlutil.joinpath(current.rooturl, indexname)

    def get_user_url(self):
        return self.current.getuserurl(self.http.auth[0])

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


class MyArgumentParser(argparse.ArgumentParser):
    class ArgumentError(Exception):
        """ and error from the argparse subsystem. """
    def error(self, error):
        """raise errors instead of printing and raising SystemExit"""
        raise self.ArgumentError(error)

def try_argcomplete(parser):
    try:
        import argcomplete
    except ImportError:
        pass
    else:
        argcomplete.autocomplete(parser)

def parse_args(argv):
    argv = map(str, argv)
    parser = getbasebaser(argv[0])
    add_subparsers(parser)
    try_argcomplete(parser)
    try:
        return parser.parse_args(argv[1:])
    except parser.ArgumentError as e:
        if not argv[1:]:
            return parser.parse_args(["-h"])
        parser.print_usage()
        parser.exit(2, "%s: error: %s\n" % (parser.prog, e.args[0]))

def add_subparsers(parser):
    subparsers = parser.add_subparsers()
    for func, args, kwargs in subcommand.discover(globals()):
        if len(args) > 1:
            name = args[1]
        else:
            name = func.__name__
        subparser = subparsers.add_parser(name, help=func.__doc__)
        subparser.Action = argparse.Action
        add_generic_options(subparser)
        func(subparser)
        mainloc = args[0]
        subparser.set_defaults(mainloc=mainloc)
    #subparser = subparsers.add_parser("_test", help=argparse.SUPPRESS)
    #subparser.set_defaults(mainloc="devpi")

def getbasebaser(prog):
    parser = MyArgumentParser(prog=prog)
    add_generic_options(parser)
    return parser

def add_generic_options(parser):
    group = parser.add_argument_group("generic options")
    group.add_argument("--version", action="version",
                       version="devpi-server-" + __version__)
    group.add_argument("--debug", action="store_true",
        help="show debug messages including more info on server requests")
    #group.add_argument("-v", "--verbose", action="store_true",
    #    help="increase verbosity")
    group.add_argument("--clientdir", action="store", metavar="DIR",
        default=os.path.expanduser(os.environ.get("DEVPI_CLIENTDIR",
                                                  "~/.devpi/client")),
        help="directory for storing login and other state")

@subcommand("devpi.use")
def use(parser):
    """ show or configure remote index and target venv for install
    activities. """

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
    """ show remote server and index configuration. """
    parser.add_argument("path", nargs="?",
        help="path to a resource to show information on. "
             "examples: '/', '/user', '/user/index'.")

@subcommand("devpi.user")
def user(parser):
    """ add, remove, modify, list user configuration"""
    group = parser.add_argument_group()
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
        help="key=value configuration item")

@subcommand("devpi.login")
def login(parser):
    """ login to devpi-server"""
    parser.add_argument("--password", action="store", default=None,
                        help="password to use for login (prompt if not set)")
    parser.add_argument("username", action="store", default=None,
                        help="username to use for login")

@subcommand("devpi.login:logoff")
def logoff(parser):
    """ log out of the current devpi-server"""

@subcommand("devpi.index")
def index(parser):
    """ create, delete and manage indexes. """
    group = parser.add_mutually_exclusive_group()
    group.add_argument("-c", "--create", action="store_true",
        help="create an index")
    group.add_argument("--delete", action="store_true",
        help="delete an index")
    group.add_argument("-m", "--modify", action="store_true",
        help="modify an index")
    group.add_argument("-l", "--list", action="store_true",
        help="list indexes for the logged in user")
    parser.add_argument("indexname", type=str, action="store", nargs="?",
        help="index name, specified as NAME or USER/NAME")
    parser.add_argument("keyvalues", nargs="*", type=str,
        help="key=value configuration item")

@subcommand("devpi.upload.upload")
def upload(parser):
    """ prepare and upload packages to the current index. """
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
             "Examples sdist.zip,bdist_egg,bdist_dumb.")
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
        help="perform upload_docs in addition to uploading release files")
    parser.add_argument("--only-docs", action="store_true", default=None,
        dest="onlydocs",
        help="perform only upload_docs and no release files")
    #parser.add_argument("-y", dest="yes",
    #    action="store_true", default=None,
    #    help="answer yes on interactive questions. ")
    #

@subcommand("devpi.test.test")
def test(parser):
    """ download and test a package against tox environments."""
    parser.add_argument("-e", metavar="VENV", type=str, dest="venv",
        default=None, action="store",
        help="virtual environment to run from the tox.ini")

    parser.add_argument("pkgspec", metavar="pkgspec", type=str,
        default=None, action="store", nargs=1,
        help="package specification to download and test")

@subcommand("devpi.push")
def push(parser):
    """ push a release and releasefiles to an external index server.
        (pushing between indexes not implemented yet).
    """
    parser.add_argument("--pypirc", metavar="path", type=str,
        default=None, action="store",
        help="path to pypirc")
    parser.add_argument("nameversion", metavar="NAME-VER", type=str,
        default=None, action="store",
        help="release in format 'name-version'. of which the metadata and "
             "all release files are to be uploaded to the specified "
             "external pypi repo." )
    parser.add_argument("-r", dest="posturl", metavar="url", type=str,
        default=None, action="store",
        help="repo name as specified in your .pypirc file")
    #parser.add_argument("targetindex", type=str, default=None, nargs="?",
    #    help="index in USER/NAME form to push to. ")


@subcommand("devpi.install")
def install(parser):
    """ install packages through current devpi index. """
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
    """ commands for controling the automatic server. """
    parser.add_argument("--stop", action="store_true",
        help="stop automatically started server if any")
    parser.add_argument("--log", action="store_true",
        help="show last log lines of automatic server")


if __name__ == "__main__":
    main()
