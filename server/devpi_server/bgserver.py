"""
interact/control devpi-server background process.
"""
from __future__ import unicode_literals
import sys
import os
import time
import py
import contextlib

from devpi_common.url import urlparse

from devpi_server.vendor.xprocess import XProcess
from devpi_common.request import new_requests_session


def getnetloc(url, scheme=False):
    parsed = urlparse(url)
    netloc = parsed.netloc
    if netloc.endswith(":80"):
        netloc = netloc[:-3]
    if scheme:
        netloc = "%s://%s" %(parsed.scheme, netloc)
    return netloc


class BackgroundServer:
    def __init__(self, tw, xprocdir):
        self.tw = tw
        self._extlogfiles = {}
        self.xproc = XProcess(config=self, rootdir=xprocdir)
        self.info = self.xproc.getinfo("devpi-server")

    def fatal(self, msg):
        self.tw.line(msg, red=True)
        raise SystemExit(1)

    def line(self, msg, **kw):
        self.tw.line(msg, **kw)

    def _waitup(self, url, count=1800):
        # try to start devpi-server (which remotely
        # receives a serials list which may take a while)
        session = new_requests_session()
        with no_proxy(urlparse(url).netloc):
            while count > 0:
                if not self.xproc.getinfo("devpi-server").isrunning():
                    return False
                try:
                    session.get(url)
                except session.Errors:
                    time.sleep(0.1)
                    count -= 1
                else:
                    return True
        return False

    def start(self, args, argv):
        filtered_args = [x for x in argv if x not in ("--start", "--init")]
        devpi_server = sys.argv[0]
        if devpi_server is None:
            self.fatal("cannot find devpi-server binary, no auto-start")
        devpi_server = os.path.abspath(devpi_server)
        if devpi_server.endswith(".py") and sys.platform == "win32":
            devpi_server = str(py.path.local.sysfind("devpi-server"))
        if not (py.path.local(devpi_server).exists()
                or py.path.local(devpi_server + '.exe').exists()):
            self.fatal("not existing devpi-server: %r" % devpi_server)

        url = "http://%s:%s" % (args.host, args.port)
        if self._waitup(url, count=1):
            self.fatal("a server is already running at %s" % url)

        def prepare_devpiserver(cwd):
            self.line("starting background devpi-server at %s" % url)
            argv = [devpi_server, ] + filtered_args
            return (lambda: self._waitup(url), argv)
        self.xproc.ensure("devpi-server", prepare_devpiserver)
        info = self.xproc.getinfo("devpi-server")
        self.pid = info.pid
        self.logfile = info.logpath
        self.line("logfile is at %s" % self.logfile)

    def stop(self):
        info = self.xproc.getinfo("devpi-server")
        ret = info.kill()
        if ret == 1:
            self.line("killed server pid=%s" % info.pid)
            return 0
        elif ret == -1:
            self.line("failed to kill server pid=%s" % info.pid, red=True)
            return 1
        self.line("no server found", red=True)
        return 0

    def log(self):
        logpath = self.info.logpath
        if not logpath.check():
            self.line("no logfile found at: %s" % logpath, red=True)
            return
        with logpath.open("r") as f:
            try:
                f.seek(-30*100, 2)
            except IOError:
                pass
            self.line("last lines of devpi-server log", bold=True)
            lines = f.readlines()
            for line in lines[1:]:
                self.line(line.rstrip())
            self.line("logfile at: %s" % logpath, bold=True)


@contextlib.contextmanager
def no_proxy(netloc):
    saved = dict(no_proxy=os.environ.pop("no_proxy", None))
    if not sys.platform.startswith("win"):
        saved["NO_PROXY"] = os.environ.pop("NO_PROXY", None)

    try:
        os.environ["no_proxy"] = netloc
        yield
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
