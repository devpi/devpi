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
    index = configproperty("index")
    simpleindex = configproperty("simpleindex")
    pypisubmit = configproperty("pypisubmit")
    login = configproperty("login")
    resultlog = configproperty("resultlog")
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
        for name in ("index", "simpleindex", "pypisubmit",
                     "resultlog", "login", "venvdir"):
            yield (name, getattr(self, name))

    def reconfigure(self, data, merge=False):
        self._raw = data
        if not merge:
            self._configdict.clear()
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
        return urlutil.joinpath(self.login, "/")

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

    def configure_fromurl(self, hub, url):
        url = hub.get_index_url(url)
        data = hub.http_api("get", url.rstrip("/") + "/+api")
        if data["status"] == 200:
            data = data["result"]
            for name in data:
                data[name] = urlutil.joinpath(url, data[name])
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
        hub.debug("config: %s" % config.path)
    else:
        hub.debug("no config file, using empty defaults")

    if args.venv:
        venvname = args.venv
        cand = hub.cwd.join(venvname, abs=True)
        if not cand.check():
            cand = hub.path_venvbase.join(venvname)
            if not cand.check():
                hub.fatal("no virtualenv %r found" % venvname)
        config.reconfigure(dict(venvdir=cand.strpath), merge=True)

    if args.use:
        config.configure_fromurl(hub, args.use)

    showurls = args.urls or args.debug

    path = args.path
    if path:
        if path[0] != "/":
            if not config.index:
                hub.fatal("cannot use relative path without an active index")
            url = urlutil.joinpath(hub.get_index_url(), path)
        else:
            url = urlutil.joinpath(config.rooturl, path)
        data = hub.http_api("get", url, quiet=True)
        hub.out_json(data)
        return

    if config.rooturl and config.rooturl != "/":
        if showurls or not config.index:
            hub.info("connected to: " + config.rooturl)
    else:
        if not args.venv:
            hub.fatal("not connected to any devpi instance, "
                      "use devpi --use URL")

    if showurls:
        for name, value in config.items():
            hub.info("%16s: %s" %(name, value))
    else:
        if not config.index:
            hub.error("not using any index (use 'index -l')")
        else:
            hub.info("using index: " + config.index)

    if hub.http.auth:
        user, password = hub.http.auth
        hub.info("logged in as: %s" % user)
    else:
        hub.line("not currently logged in")


def parse_keyvalue_spec(keyvaluelist, keyset=None):
    d = {}
    for x in keyvaluelist:
        key, val = x.split("=", 1)
        if keyset and key not in keyset:
            raise KeyError("invalid key: %s, allowed: %s" % (key, keyset))
        d[key] = val
    return d
