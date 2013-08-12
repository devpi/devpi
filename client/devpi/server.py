
"""
interact/control automatic server.
"""
import os
import time
import py

from devpi.util import url as urlutil
from devpi._vendor.xprocess import XProcess

default_rooturl = "http://localhost:3141"

class AutoServer:
    def __init__(self, hub):
        self.hub = hub
        self._extlogfiles = {}
        xprocdir = hub.clientdir.join("xproc")
        # let's move the pre-0.9.2 .xproc dir to the new location
        xprocdir_old = hub.clientdir.join(".xproc")
        if xprocdir_old.check() and not xprocdir.check():
            xprocdir_old.move(xprocdir)
        self.xproc = XProcess(config=self, rootdir=xprocdir, log=hub)
        self.info = self.xproc.getinfo("devpi-server")

    def _waitup(self, url, count=50):
        while count > 0:
            try:
                r = self.hub.http.get(url)
            except self.hub.http.ConnectionError as e:
                time.sleep(0.05)
                count -= 1
            else:
                return True
        return False

    def start(self, datadir, default_rooturl=default_rooturl, removedata=False):
        devpi_server = py.path.local.sysfind("devpi-server")
        if devpi_server is None:
            self.hub.fatal("cannot find devpi-server binary, no auto-start")
        def prepare_devpiserver(cwd):
            parts = urlutil.getnetloc(default_rooturl).split(":")
            if len(parts) == 1:
                port = "80"
            else:
                port = parts[1]
            url = "http://localhost:%s" % port
            self.hub.info("automatically starting devpi-server at %s" % url)
            if datadir is None:
                serverdir = cwd.join("data")
                if removedata and serverdir.check():
                    serverdir.remove()
            else:
                serverdir = py.path.local(datadir)
            serverdir.ensure(dir=1)
            return (lambda: self._waitup(url),
                [devpi_server, "--debug", "--data", serverdir, "--port", port])
        self.xproc.ensure("devpi-server", prepare_devpiserver)
        info = self.xproc.getinfo("devpi-server")
        self.pid = info.pid
        self.logfile = info.logpath
        self.hub.debug("*** logfile is at %s" % self.logfile)

    def stop(self, withlog=None):
        info = self.xproc.getinfo("devpi-server")
        ret = info.kill()
        if ret == 1:
            if withlog:
                withlog.info("killed automatic server pid=%s" % info.pid)
            return 0
        elif ret == -1:
            if withlog:
                withlog.error("failed to kill automatic server pid=%s" %
                              info.pid)
            return 1
        if withlog:
            withlog.info("no server found")
        return 0

    def log(self):
        logpath = self.info.logpath
        if not logpath.check():
            self.hub.error("no logfile found at: %s" % logpath)
            return
        with logpath.open("r") as f:
            try:
                f.seek(-30*100, 2)
            except IOError:
                pass
            self.hub.info("last lines of devpi-server log")
            lines = f.readlines()
            for line in lines[1:]:
                self.hub.line(line.rstrip())
            self.hub.info("logfile at: %s" % logpath)

def main(hub, args):
    autoserver = AutoServer(hub)
    if args.start:
        from devpi_server.config import get_default_serverdir
        datadir = get_default_serverdir()
        datadir = py.path.local(os.path.expanduser(datadir))
        ret = autoserver.start(datadir=datadir)
        return ret
    if args.stop:
        ret = autoserver.stop(withlog=hub)
        return ret
    elif args.log:
        autoserver.log()
    if autoserver.info.isrunning():
        hub.info("automatic server is running with pid %s" %
                 autoserver.info.pid)
    else:
        hub.info("no automatic server is running")
