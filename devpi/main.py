import os
import sys
import py
import argparse
import subprocess
from devpi.util.lazydecorator import lazydecorator
from devpi import log
from devpi.use import Config
std = py.std
subcommand = lazydecorator()

def main(argv=None):
    if argv is None:
        argv = list(sys.argv)
    args = parse_args(argv)
    mod = __import__(args.mainloc, None, None, ["__doc__"])
    hub = Hub(debug=args.debug)
    #log._setdefault(hub.getdefaultlog)
    #with log(info=hub.info, error=hub.error, debug=hub.debug):
    return getattr(mod, "main")(hub, args)

class Hub:
    class Popen(std.subprocess.Popen):
        STDOUT = std.subprocess.STDOUT
        PIPE = std.subprocess.PIPE
        def __init__(self, cmds, *args, **kwargs):
            cmds = [str(x) for x in cmds]
            std.subprocess.Popen.__init__(self, cmds, *args, **kwargs)

    def __init__(self, cwd=None, debug=False):
        self._tw = py.io.TerminalWriter()
        self._debug = debug
        if cwd is None:
            cwd = py.path.local()
        self.cwd = cwd

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

    @property
    def config(self):
        try:
            return self._config
        except AttributeError:
            self._config = Config.from_path(self.cwd)
            return self._config

    @property
    def remoteindex(self):
        try:
            return self._remoteindex
        except AttributeError:
            from devpi.remoteindex import RemoteIndex
            self._remoteindex = RemoteIndex(self.config)
            return self._remoteindex

    @property
    def path_venvbase(self):
        path = os.environ.get("WORKON_HOME", None)
        if path is None:
            return
        return py.path.local(path)

    def getdefaultlog(self, name):
        if name in ("error", "fatal", "info"):
            return getattr(self, name)
        if self._debug:
            def logdebug(*msg):
                self.line("[debug:%s]" % name, *msg)
        else:
            def logdebug(*msg):
                pass
        return logdebug

    def popen_output(self, args, cwd=None):
        if isinstance(args, str):
            args = std.shlex.split(args)
        assert args[0], args
        args = [str(x) for x in args]
        if cwd == None:
            cwd = self.cwd
        self.line("%s$" % cwd, " ".join(args), "[to-pipe]")
        return subprocess.check_output(args, cwd=str(cwd))

    def popen_check(self, args):
        assert args[0], args
        args = [str(x) for x in args]
        self.line("$", " ".join(args))
        return subprocess.check_call(args)

    def line(self, *msgs, **kwargs):
        msg = " ".join(map(str, msgs))
        self._tw.line(msg, **kwargs)

    def debug(self, *msg):
        if self._debug:
            self.line("[debug]", *msg)

    def error(self, *msg):
        self.line(*msg, red=True)

    def fatal(self, *msg):
        self.line(*msg, red=True)
        raise SystemExit(1)

    def info(self, *msg):
        self.line(*msg, bold=True)


def parse_args(argv):
    argv = map(str, argv)
    parser = argparse.ArgumentParser(prog=argv[0])
    subparsers = parser.add_subparsers()

    for func, args, kwargs in subcommand.discover(globals()):
        subparser = subparsers.add_parser(func.__name__, help=func.__doc__)
        subparser.Action = argparse.Action
        add_generic_options(subparser)
        func(subparser)
        mainloc = args[0]
        subparser.set_defaults(mainloc=mainloc)

    args = parser.parse_args(argv[1:])
    return args

def add_generic_options(parser):
    parser.add_argument("--debug", action="store_true",
        help="show debug messages")

@subcommand("devpi.use")
def use(parser):
    """ show, create or delete configuration information. """
    parser.add_argument("--delete", action="store_true",
        help="delete currently stored API information")
    parser.add_argument("indexurl", metavar="URL", type=str,
        action="store", nargs="*",
        help="url for retrieving index API information. ")

@subcommand("devpi.index")
def index(parser):
    """ create, delete and manage indexes. """
    group = parser.add_mutually_exclusive_group()
    group.add_argument("-c", "--create", action="store_true", dest="create",
        help="create index ")
    group.add_argument("--delete", action="store_true",
        help="delete index")
    group.add_argument("--configure", action="store_true", dest="configure",
        help="configure index")
    parser.add_argument("indexname", type=str,
        action="store", nargs=1,
        help="index name, specified as user/iname")
    parser.add_argument("keyvalues", type=str,
        action="store", nargs="*",
        help="key=value configuration items")

@subcommand("devpi.upload.upload")
def upload(parser):
    """ prepare and upload packages to the current index. """
    parser.add_argument("-l", dest="showstatus",
        action="store_true", default=None,
        help="show remote versions, local version and package types")
    parser.add_argument("--ver", dest="setversion",
        action="store", default=None,
        help="set version to fill into setup.py and package files")
    #parser.add_argument("-y", dest="yes",
    #    action="store_true", default=None,
    #    help="answer yes on interactive questions. ")

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
    """ push a release and releasefiles to another index server. """
    parser.add_argument("--pypirc", metavar="path", type=str,
        default=None, action="store",
        help="path to pypirc")
    parser.add_argument("nameversion", metavar="release", type=str,
        default=None, action="store",
        help="release of format 'name-version' to push")
    parser.add_argument("posturl", metavar="url", type=str,
        default=None, action="store",
        help="post url of other index server.")


@subcommand("devpi.install")
def install(parser):
    """ install packages through current devpi index. """
    parser.add_argument("-l", action="store_true", dest="listinstalled",
        help="print list of currently installed packages. ")
    parser.add_argument("pkgspecs", metavar="pkg", type=str,
        action="store", default=None, nargs="*",
        help="uri or package file for installation from current index. """
    )


if __name__ == "__main__":
    main()
