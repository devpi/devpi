import os
import sys
import py

from devpi import log
from devpi.util import url as urlutil
import posixpath

if sys.platform == "win32":
    vbin = "Scripts"
else:
    vbin = "bin"


class Config:
    CONFIGBASENAME = ".devpiconfig"

    def __init__(self, simpleindex="", pypisubmit="", pushrelease="",
                       resultlog="", login="",
                       venvdir=None, path=None):
        self.simpleindex = simpleindex
        self.login = login
        self.pypisubmit = pypisubmit
        self.pushrelease = pushrelease
        self.resultlog = resultlog
        self.venvdir = venvdir
        self.setpath(path)

    @property
    def rooturl(self):
        return urlutil.joinpath(self.simpleindex, "/")

    def getuserurl(self, user):
        return urlutil.joinpath(self.rooturl, user)

    def setpath(self, path):
        if path and path.basename != self.CONFIGBASENAME:
            path = path.join(self.CONFIGBASENAME)
        self.path = path

    def exists(self):
        return self.path and self.path.check()

    @classmethod
    def from_path(cls, path=None):
        config = cls()
        config.configure_frompath(path)
        return config

    def items(self):
        for name in ("simpleindex", "pypisubmit", "pushrelease",
                     "login", "resultlog", "venvdir"):
            yield (name, getattr(self, name))

    def _normalize_url(self, url):
        url = url.rstrip("/") + "/"
        if not urlutil.ishttp(url):
            base = urlutil.getnetloc(self.simpleindex, scheme=True)
            url = urlutil.joinpath(base, url)
        return url

    def configure_fromurl(self, url):
        url = self._normalize_url(url)
        newurl = urlutil.joinpath(url, "-api")
        log.debug("retrieving api configuration from", newurl)
        f = py.std.urllib.urlopen(newurl)
        data = py.std.json.loads(f.read())
        for name in data:
            data[name] = urlutil.joinpath(newurl, data[name])
        self._reconfig(**data)

    def _reconfig(self, **data):
        for name in data:
            oldval = getattr(self, name)
            newval = data[name]
            if oldval != newval:
                if name == "venvdir":
                    newval = py.path.local(newval)
                setattr(self, name, newval)
                #log.debug("changing", name, "to", newval)

    def configure_frompath(self, path=None):
        if path is None:
            path = py.path.local()
        newpath = self.__class__._findpath(path)
        if newpath is not None:
            apidict = py.std.json.loads(newpath.read())
            self._reconfig(path=newpath, **apidict)
            log.debug("configure_frompath: configuration loaded from %s",
                      newpath)
            return True
        else:
            log.debug("configure_frompath: no configuration detected")
            return False

    @classmethod
    def _findpath(cls, path):
        old = None
        while path != old:
            candidate = path.join(cls.CONFIGBASENAME)
            if candidate.check():
                return candidate
            old = path
            path = path.dirpath()

    def save(self):
        p = self.path.ensure()
        apidict = dict(simpleindex=self.simpleindex,
                       pypisubmit=self.pypisubmit,
                       pushrelease=self.pushrelease,
                       login=self.login,
                       resultlog=self.resultlog,
                       venvdir=getattr(self.venvdir, "strpath", self.venvdir))
        p.write(py.std.json.dumps(apidict))
        log.debug("saved config", p)

    def getvenvbin(self, name):
        if self.venvdir:
            return py.path.local.sysfind(name, paths=[self.venvdir.join(vbin)])
        return py.path.local.sysfind(name)

def getvenv():
    pip = py.path.local.sysfind("pip")
    if pip is None:
        return None
    return pip.dirpath().dirpath()

def getconfig(path=None):
    if path is None:
        path = py.path.local()
    config = Config()
    if config.configure_frompath(path):
        return config

def main(hub, args):
    config = hub.config
    if args.delete:
        if not config.exists():
            hub.error_and_out("NO configuration found")
        config.path.remove()
        hub.info("REMOVED configuration at", config.path)
        return
    if config.exists():
        msg = "config:"
    else:
        msg = "creating config"
        config.setpath(hub.cwd)
    hub.info(msg, py.path.local().bestrelpath(config.path))

    if args.indexurl:
        assert not args.delete
        for arg in args.indexurl:
            if arg.startswith("venv="):
                venvname = arg[5:]
                cand = hub.cwd.join(venvname, abs=True)
                if not cand.check():
                    cand = hub.path_venvbase.join(venvname)
                    if not cand.check():
                        hub.fatal("no virtualenv %r found" % venvname)
                config._reconfig(venvdir=cand)
            else:
                config.configure_fromurl(arg)
        config.save()
    for name, value in config.items():
        hub.info("%16s: %s" %(name, value))

    if hub.http.auth:
        user, password = hub.http.auth
        hub.info("currently logged in as: %s" % user)
    else:
        hub.info("not currently logged in")

def parse_keyvalue_spec(keyvaluelist, keyset):
    d = {}
    for x in keyvaluelist:
        key, val = x.split("=", 1)
        if key not in keyset:
            raise KeyError("invalid key: %s, allowed: %s" % (key, keyset))
        d[key] = val
    return d
