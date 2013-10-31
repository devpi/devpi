from __future__ import unicode_literals
import sys
import subprocess
import py
from .main import fatal
from devpi_common.proc import check_output


def check_call(args):
    return subprocess.check_call([str(x) for x in args])

class VirtualenvDir:
    def __init__(self, venvdir, tw):
        self.venvdir = venvdir
        self.tw = tw

    def create(self):
        virtualenv = py.path.local.sysfind("virtualenv")
        if not virtualenv:
            fatal("need 'virtualenv' to create virtualenv")
        check_call([virtualenv, "-q",  self.venvdir])

    @property
    def bin(self):
        bin = self.venvdir.join("bin" if sys.platform != "win32" else "Scripts")
        assert bin.exists()
        return bin

    def find_bin(self, command):
        return py.path.local.sysfind(command, paths=[self.bin])

    def _getargs(self, args):
        args = [str(x) for x in args]
        command = args[0]
        cmd = self.find_bin(command)
        if not cmd:
            fatal("command %r not found" % cmd)
        args[0] = str(cmd)
        return args

    def check_output(self, args):
        args = self._getargs(args)
        self.tw.line("$ %s [captured]" % " ".join(args))
        return check_output(args)

    def check_call(self, args):
        args = self._getargs(args)
        self.tw.line("$ %s" % " ".join(args))
        return check_call(args)


def create_server_venv(tw, serverversion, venv_dir):
    venv = VirtualenvDir(venv_dir, tw)
    venv.create()
    parts = serverversion.split(".")
    major, minor = map(int, parts[:2])
    venv.check_call(["pip", "install", "--pre",
                     "devpi-server>=%s,<%s" % ("%s.%s" % (major,minor),
                                               "%s.%s" % (major,minor+1))])
    devpiserver = venv.find_bin("devpi-server")
    assert devpiserver
    return venv

