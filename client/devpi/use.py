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

devpi_endpoints = "index simpleindex pypisubmit resultlog login".split()

def currentproperty(name):
    def propget(self):
        return self._currentdict.get(name, None)
    def propset(self, val):
        self._currentdict[name] = val
    return property(propget, propset)

class Current(object):
    index = currentproperty("index")
    simpleindex = currentproperty("simpleindex")
    pypisubmit = currentproperty("pypisubmit")
    login = currentproperty("login")
    resultlog = currentproperty("resultlog")
    venvdir = currentproperty("venvdir")
    _auth = currentproperty("auth")

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

    def _get_auth_dict(self):
        auth = self._auth
        if not isinstance(auth, dict):
            auth = {}
        return auth

    def set_auth(self, user, password, url=None):
        if url is None:
            url = self.rooturl
        auth = self._get_auth_dict()
        auth[url] = (user, password)
        self.reconfigure(data=dict(_auth=auth))

    def del_auth(self, url=None):
        if url is None:
            url = self.rooturl
        auth = self._get_auth_dict()
        try:
            del auth[url]
        except KeyError:
            return False
        self.reconfigure(data=dict(_auth=auth))
        return True

    def get_auth_user(self):
        return self._get_auth_dict().get(self.rooturl, [None])[0]

    def get_auth(self, url=None):
        url = url if url is not None else self.rooturl
        auth = self._get_auth_dict().get(url)
        return tuple(auth) if auth else None

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

    def exists(self):
        return self.path and self.path.check()

    def _normalize_url(self, url):
        url = url.rstrip("/") + "/"
        if not urlutil.ishttp(url):
            base = urlutil.getnetloc(self.simpleindex, scheme=True)
            url = urlutil.joinpath(base, url)
        return url

    def configure_fromurl(self, hub, url):
        url = self.get_index_url(url)
        if not urlutil.is_valid_url(url):
            hub.fatal("invalid URL: %s" % url)
        r = hub.http_api("get", url.rstrip("/") + "/+api", quiet=True,
                         auth=None)
        rooturl = urlutil.getnetloc(url, scheme=True)
        result = r["result"]
        data = {}
        url_keys = set(devpi_endpoints)
        for name in url_keys:
            val = result.get(name, None)
            if val is not None:
                val = urlutil.joinpath(rooturl, val)
            data[name] = val
        self.reconfigure(data)

    def getvenvbin(self, name, venvdir=None, glob=True):
        if venvdir is None:
            venvdir = self.venvdir
        if venvdir:
            bindir = py.path.local(venvdir).join(vbin)
            return py.path.local.sysfind(name, paths=[bindir])
        if glob:
            return py.path.local.sysfind(name)

    # url helpers
    #
    @property
    def rooturl(self):
        if self.login:
            return urlutil.joinpath(self.login, "/")

    def get_user_url(self, user=None):
        if user is None:
            user = self.get_auth_user()
            if not user:
                raise ValueError("no current authenticated user")
        return urlutil.joinpath(self.rooturl, user)

    def get_index_url(self, indexname=None, slash=True):
        if indexname is None:
            indexname = self.index
            if indexname is None:
                raise ValueError("no index name")
        if "/" not in indexname:
            userurl = self.get_user_url()
            return urlutil.joinpath(userurl + "/", indexname)
        url = urlutil.joinpath(self.rooturl, indexname)
        url = url.rstrip("/")
        if slash:
            url = url.rstrip("/") + "/"
        return url

    def get_project_url(self, name):
        baseurl = self.get_index_url(slash=True)
        url = urlutil.joinpath(baseurl, name) + "/"
        return url

def out_index_list(hub, data):
    for user in data:
        indexes = data[user].get("indexes", [])
        for index, ixconfig in indexes.items():
            hub.info("%s/%s: bases=%s" %(user, index,
                     ",".join(ixconfig.get("bases", []))))
    return

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
    if args.list:
        if not hub.current.rooturl:
            hub.fatal("not connected to any server")
        r = hub.http_api("GET", hub.current.rooturl, {}, quiet=True)
        out_index_list(hub, r["result"])
        return 0

    showurls = args.urls or args.debug

    user = current.get_auth_user()
    if user:
        login_status = "logged in as %s" % user
    else:
        login_status = "not logged in"
    if current.rooturl:
        if current.index:
            if showurls:
                for name in devpi_endpoints:
                    hub.info("%16s: %s" %(name, getattr(current, name)))
            else:
                hub.info("using index: %s (%s)" % (current.index, login_status))
        elif current.rooturl:
            hub.info("using server: %s (%s)" % (current.rooturl, login_status))
            hub.line("no current index: type 'devpi use -l' "
                      "to discover indices")
    else:
        hub.line("no server: type 'devpi use URL' with a URL "
                 "pointing to a server or directly to an index.")
    if current.venvdir:
        hub.info("venv for install command: %s" % current.venvdir)
    #else:
    #    hub.line("no current install venv set")



def parse_keyvalue_spec(keyvaluelist, keyset=None):
    d = {}
    for x in keyvaluelist:
        key, val = x.split("=", 1)
        if keyset and key not in keyset:
            raise KeyError("invalid key: %s, allowed: %s" % (key, keyset))
        d[key] = val
    return d
