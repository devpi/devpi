import os
import sys
import py

import json

from devpi import log, cached_property
from devpi.util import url as urlutil
from devpi.server import handle_autoserver
import posixpath

if sys.platform == "win32":
    vbin = "Scripts"
else:
    vbin = "bin"

def is_valid_url(url):
    result = urlutil.urlparse(url)
    return result.scheme in ("http", "https") and result.netloc

def currentproperty(name):
    def propget(self):
        return self._currentdict.get(name, None)
    def propset(self, val):
        self._currentdict[name] = val
    return property(propget, propset)

class Current(object):
    index = currentproperty("index")
    simpleindex = currentproperty("simpleindex")
    bases = currentproperty("bases")
    pypisubmit = currentproperty("pypisubmit")
    login = currentproperty("login")
    resultlog = currentproperty("resultlog")
    venvdir = currentproperty("venvdir")
    auth = currentproperty("auth")

    def __init__(self, path):
        self.path = path
        self._setupcurrentdict()

    def _setupcurrentdict(self):
        self._currentdict = d = {}
        if self.path.check():
            log.debug("loading current from %s" % self.path)
            d.update(json.loads(self.path.read()))
        else:
            log.debug("no client config found at %s" % self.path)

    def reconfigure(self, data):
        for name in data:
            oldval = getattr(self, name)
            newval = data[name]
            if oldval != newval:
                setattr(self, name, newval)
                log.info("changing %r to %r", name, newval)
        log.debug("writing current %s", self.path)
        oldumask = os.umask(7*8+7)
        try:
            self.path.write(json.dumps(self._currentdict))
        finally:
            os.umask(oldumask)

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
        url = hub.get_index_url(url, current=self)
        if not is_valid_url(url):
            hub.fatal("invalid URL: %s" % url)
        r = hub.http_api("get", url.rstrip("/") + "/+api", quiet=True)
        assert r.status_code == 200
        data = {}
        rooturl = urlutil.getnetloc(url, scheme=True)
        for name in r["result"]:
            data[name] = urlutil.joinpath(rooturl, r["result"][name])
        self.reconfigure(data)

    def getvenvbin(self, name, venvdir=None, glob=True):
        if venvdir is None:
            venvdir = self.venvdir
        if venvdir:
            bindir = py.path.local(venvdir).join(vbin)
            return py.path.local.sysfind(name, paths=[bindir])
        if glob:
            return py.path.local.sysfind(name)


def getvenv():
    pip = py.path.local.sysfind("pip")
    if pip is None:
        return None
    return pip.dirpath().dirpath()

def main(hub, args=None):
    args = hub.args
    current = hub.current

    if args.delete:
        if not hub.current.exists():
            hub.error_and_out("NO configuration found")
        hub.current.path.remove()
        hub.info("REMOVED configuration at", hub.current.path)
        return
    if current.exists():
        hub.debug("current: %s" % current.path)
    else:
        hub.debug("no current file, using defaults")

    if not args.noauto:
        handle_autoserver(hub, current, target=args.url)
    if args.url:
        current.configure_fromurl(hub, args.url)
    elif current.index:  # re-get status/api
        current.configure_fromurl(hub, current.index)

    if args.venv:
        if args.venv != "-":
            venvname = args.venv
            cand = hub.cwd.join(venvname, vbin, abs=True)
            if not cand.check():
                cand = hub.path_venvbase.join(venvname, vbin)
                if not cand.check():
                    hub.fatal("no virtualenv %r found" % venvname)
            current.reconfigure(dict(venvdir=cand.dirpath().strpath))
        else:
            current.reconfigure(dict(venvdir=None))

    showurls = args.urls or args.debug

    if current.rooturl and current.rooturl != "/":
        if showurls or not current.index:
            hub.info("connected to: " + current.rooturl)

    if showurls:
        for name in "index simpleindex pypisubmit resultlog login".split():
            hub.info("%16s: %s" %(name, getattr(current, name)))
    else:
        if not current.index:
            hub.error("not using any index (use 'index -l')")
        else:
            hub.info("using index:  " + current.index)
    if current.venvdir:
        hub.info("install venv: %s" % current.venvdir)
    else:
        hub.line("no current install venv set")

    if current.auth:
        user, password = current.auth
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
