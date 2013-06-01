import os
import sys
import py

import json

from devpi import log, cached_property
from devpi.util import url as urlutil
import posixpath

if sys.platform == "win32":
    vbin = "Scripts"
else:
    vbin = "bin"


def configproperty(name):
    def propget(self):
        return self._configdict.get(name, None)
    def propset(self, val):
        self._configdict[name] = val
    return property(propget, propset)

class Config(object):
    simpleindex = configproperty("simpleindex")
    pypisubmit = configproperty("pypisubmit")
    pushrelease = configproperty("pushrelease")
    resultlog = configproperty("resultlog")
    login = configproperty("login")
    venvdir = configproperty("venvdir")

    def __init__(self, path):
        self.path = path
        self._setupconfigdict()

    def _setupconfigdict(self):
        self._configdict = d = {}
        if self.path.check():
            log.debug("loading config from %s", self.path)
            d.update(json.loads(self.path.read()))

    def items(self):
        for name in ("simpleindex", "pypisubmit", "pushrelease",
                     "login", "resultlog", "venvdir"):
            yield (name, getattr(self, name))

    def reconfigure(self, data):
        for name in data:
            oldval = getattr(self, name)
            newval = data[name]
            if oldval != newval:
                setattr(self, name, newval)
                log.debug("changing %r to %r", name, newval)
        log.debug("writing config %s", self.path)
        self.path.write(json.dumps(self._configdict))

    @property
    def rooturl(self):
        return urlutil.joinpath(self.simpleindex, "/")

    def getuserurl(self, user):
        return urlutil.joinpath(self.rooturl, user)

    def exists(self):
        return self.path and self.path.check()

    def _normalize_url(self, url):
        url = url.rstrip("/") + "/"
        if not urlutil.ishttp(url):
            base = urlutil.getnetloc(self.simpleindex, scheme=True)
            url = urlutil.joinpath(base, url)
        return url

    def configure_fromurl(self, url):
        url = self._normalize_url(url)
        newurl = urlutil.joinpath(url, "-api")
        log.debug("retrieving api configuration from %s", newurl)
        f = py.std.urllib.urlopen(newurl)
        data = py.std.json.loads(f.read())
        for name in data:
            data[name] = urlutil.joinpath(newurl, data[name])
        self.reconfigure(data)

    def getvenvbin(self, name):
        if self.venvdir:
            venvdir = py.path.local(venvdir)
            return py.path.local.sysfind(name, paths=[venvdir.join(vbin)])
        return py.path.local.sysfind(name)


def getvenv():
    pip = py.path.local.sysfind("pip")
    if pip is None:
        return None
    return pip.dirpath().dirpath()

def main(hub, args=None):
    config = hub.config
    args = hub.args
    if args.delete:
        if not config.exists():
            hub.error_and_out("NO configuration found")
        config.path.remove()
        hub.info("REMOVED configuration at", config.path)
        return
    if config.exists():
        msg = "config:"
    else:
        msg = "no config file, using empty defaults"
    hub.info(msg, config.path)

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
                config.reconfigure(dict(venvdir=cand.strpath))
            else:
                config.configure_fromurl(arg)
    for name, value in config.items():
        hub.info("%16s: %s" %(name, value))

    if hub.http.auth:
        user, password = hub.http.auth
        hub.info("currently logged in as: %s" % user)
    else:
        hub.info("not currently logged in")

def parse_keyvalue_spec(keyvaluelist, keyset=None):
    d = {}
    for x in keyvaluelist:
        key, val = x.split("=", 1)
        if keyset and key not in keyset:
            raise KeyError("invalid key: %s, allowed: %s" % (key, keyset))
        d[key] = val
    return d
