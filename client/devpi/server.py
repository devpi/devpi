
"""
interact/control automatic server.
"""
import os
import time
import py


from devpi.util import url as urlutil
from devpi._vendor.xprocess import XProcess, do_xkill

default_rooturl = "http://localhost:3141/"

def ensure_autoserver(hub, current):
    autoserver = AutoServer(hub)
    if current.rooturl != "/" and current.rooturl != default_rooturl:
        return
    if os.environ.get("DEVPI_NO_AUTOSERVER"):
        raise ValueError(42)
    try:
        r = hub.http.head(default_rooturl)
    except hub.http.ConnectionError as e:
        autoserver.start()
        if not current.simpleindex:
            indexurl = default_rooturl + "root/dev/"
            current.configure_fromurl(hub, indexurl)
            hub.info("auto-configuring use of root/dev index")
    else:
        hub.debug("server is running at: %s" % default_rooturl)
        r.close()

class AutoServer:
    def __init__(self, hub):
        self.hub = hub
        self._extlogfiles = {}
        xprocdir = hub.clientdir.join(".xproc")
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
            self.hub.info("automatically starting devpi-server at %s" % url)
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

    def stop(self):
        info = self.xproc.getinfo("devpi-server")
        info.kill()

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

    def stopserver(self):
        info = self.xproc.getinfo("devpi-server")
        info.kill(tw=self.hub)

def main(hub, args):
    autoserver = AutoServer(hub)
    if args.stop:
        autoserver.stop()
        return
    elif not args.nolog:
        autoserver.log()
    if autoserver.info.isrunning():
        hub.info("automatic server is running with pid %s" %
                 autoserver.info.pid)
    else:
        hub.info("no automatic server is running")
