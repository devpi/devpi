
"""
interact/control automatic server.
"""
import os
import time
import py

from devpi.util import url as urlutil
from devpi._vendor.xprocess import XProcess

default_rooturl = "http://localhost:3141"

def handle_autoserver(hub, current, target=None):
    # state changes:
    # current: default_rooturl  target: someother -> stop autoserver
    # current: someother target: default_rooturl -> start autoserver
    #
    # also if no simpleindex is defined, use /root/dev/

    autoserver = AutoServer(hub)
    current_is_root = current.rooturl == "/" or \
                      current.rooturl.startswith(default_rooturl)
    target_non_root = target and not target.startswith(default_rooturl)

    #hub.info("current_is_root: %s, target_non_root: %s" %(
    #         current_is_root, target_non_root))
    if current_is_root and target_non_root:
        autoserver.stop(withlog=hub)
        return
    if not current_is_root and (not target or target_non_root):
        return
    if os.environ.get("DEVPI_NO_AUTOSERVER"):
        raise ValueError("DEVPI_NO_AUTOSERVER prevents starting autoserver")
    try:
        r = hub._session.head(default_rooturl)
    except hub.http.ConnectionError as e:
        autoserver.start()
    else:
        hub.debug("server is already running at: %s" % default_rooturl)
        r.close()
    if not current.simpleindex:
        indexurl = default_rooturl + "/root/dev/"
        current.configure_fromurl(hub, indexurl)
        hub.info("auto-configuring use of root/dev index")

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

    def start(self, default_rooturl=default_rooturl, removedata=False):
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
            self.hub.info("automatically starting devpi-server for %s" % url)
            datadir = cwd.join("data")
            if removedata and datadir.check():
                datadir.remove()
            datadir.ensure(dir=1)
            return (lambda: self._waitup(url),
                [devpi_server, "--data", datadir, "--port", port])
        self.xproc.ensure("devpi-server", prepare_devpiserver)
        info = self.xproc.getinfo("devpi-server")
        self.pid = info.pid
        self.logfile = info.logpath

    def stop(self, withlog=None):
        info = self.xproc.getinfo("devpi-server")
        ret = info.kill()
        if withlog:
            if ret == 1:
                withlog.info("killed automatic server pid=%s" % info.pid)
            elif ret == -1:
                withlog.error("failed to kill automatic server pid=%s" %
                              info.pid)
        return ret

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
    if args.stop:
        ret = autoserver.stop(withlog=hub)
        if ret >= 0:
            return 0
        return 1
    elif args.log:
        autoserver.log()
    if autoserver.info.isrunning():
        hub.info("automatic server is running with pid %s" %
                 autoserver.info.pid)
    else:
        hub.info("no automatic server is running")
