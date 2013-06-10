
"""
interact/control automatic server.
"""
import os
import py


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
        #hub.error("no server found, starting new one")
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

    def start(self):
        devpi_server = py.path.local.sysfind("devpi-server")
        if devpi_server is None:
            self.hub.fatal("cannot find devpi-server binary, no auto-start")
        def prepare_devpiserver(cwd):
            url = default_rooturl
            self.hub.info("automatically starting devpi-server at %s" % url)
            return (".*Listening on.*", [devpi_server])
        self.xproc.ensure("devpi-server", prepare_devpiserver)
        info = self.xproc.getinfo("devpi-server")
        self.pid = info.pid
        self.logfile = info.logpath

    def stop(self):
        do_xkill(self.info, tw=self.hub)

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
        do_xkill(info, tw=self.hub)

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
