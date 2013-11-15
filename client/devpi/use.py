import os
import sys
import py
import re

import json

from devpi import log
from devpi_common.url import URL

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

def urlproperty(name):
    def propget(self):
        val = self._currentdict.get(name, None)
        if val:
            return URL(val)

    def propset(self, val):
        if isinstance(val, URL):
            val = val.url
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
    always_setcfg = currentproperty("always_setcfg")

    @property
    def index_url(self):
        if self.index:
            return URL(self.index)
        return URL("")

    def __init__(self, path):
        self.path = path
        self._currentdict = {}
        if self.path.check():
            log.debug("loading current from %s" % self.path)
            self._currentdict.update(json.loads(self.path.read()))
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
        url = URL(url, asdir=1)
        if not url.is_valid_http_url():
            url = URL(self.simpleindex, url.url).url
        return url

    def configure_fromurl(self, hub, url):
        url = self.get_index_url(url)
        if not url.is_valid_http_url():
            hub.fatal("invalid URL: %s" % url.url)
        r = hub.http_api("get", url.addpath("+api"), quiet=True)
        self._configure_from_server_api(r.result, url)

    def _configure_from_server_api(self, result, url):
        rooturl = url.joinpath("/")
        data = {}
        for name in devpi_endpoints:
            val = result.get(name, None)
            if val is not None:
                val = rooturl.joinpath(val).url
            data[name] = val
        self.reconfigure(data)
        status = result.get("authstatus", None)
        if status and status[0] not in ["ok", "noauth"]:
            self.del_auth(rooturl)

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
            return URL(self.login, ".").url

    def get_user_url(self, user=None):
        if user is None:
            user = self.get_auth_user()
            if not user:
                raise ValueError("no current authenticated user")
        return URL(self.rooturl).addpath(user)

    def get_index_url(self, indexname=None, slash=True):
        if indexname is None:
            indexname = self.index
            if indexname is None:
                raise ValueError("no index name")
        if "/" not in indexname:
            return self.get_user_url().addpath(indexname)
        if not slash:
            indexname = indexname.rstrip("/")
        return URL(self.rooturl).joinpath(indexname, asdir=slash)

    def get_project_url(self, name):
        return self.index_url.addpath(name, asdir=1)

def out_index_list(hub, data):
    for user in data:
        indexes = data[user].get("indexes", {})
        for index, ixconfig in indexes.items():
            ixname = "%s/%s" % (user, index)
            hub.info("%-15s bases=%-15s volatile=%s" %(ixname,
                     ",".join(ixconfig.get("bases", [])),
                     ixconfig["volatile"]))
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
        out_index_list(hub, r.result)
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
                hub.info("current devpi index: %s (%s)" % (current.index, login_status))
        else:
            hub.info("using server: %s (%s)" % (current.rooturl, login_status))
            hub.error("no current index: type 'devpi use -l' "
                      "to discover indices")
    else:
        hub.line("no server: type 'devpi use URL' with a URL "
                 "pointing to a server or directly to an index.")
    if current.venvdir:
        hub.info("venv for install command: %s" % current.venvdir)
    #else:
    #    hub.line("no current install venv set")
    if hub.args.always_setcfg:
        always_setcfg = hub.args.always_setcfg == "yes"
        hub.current.reconfigure(dict(always_setcfg=always_setcfg))
    if hub.args.setcfg or hub.current.always_setcfg:
        if not hub.current.index:
            hub.error("no index configured: cannot set pip/easy_install index")
        else:
            indexserver = hub.current.simpleindex
            DistutilsCfg().write_indexserver(indexserver)
            PipCfg().write_indexserver(indexserver)

    show_one_conf(hub, DistutilsCfg())
    show_one_conf(hub, PipCfg())
    hub.line("always-set-cfg: %s" % ("yes" if hub.current.always_setcfg else
                                     "no"))

def show_one_conf(hub, cfg):
    if not cfg.exists():
        status = "no config file exists"
    elif not cfg.indexserver:
        status = "no index server configured"
    else:
        status = cfg.indexserver
    hub.info("%-19s: %s" %(cfg.screen_name, status))

class BaseCfg:
    config_name = "index_url"
    regex = re.compile(r"(index[_-]url)\s*=\s*(.*)")

    def __init__(self, path=None):
        if path is None:
            path = self.default_location
        self.screen_name = str(path)
        self.path = py.path.local(path, expanduser=True)
        self.backup_path = self.path + "-bak"

    def exists(self):
        return self.path.exists()

    @property
    def indexserver(self):
        if self.path.exists():
            for line in self.path.readlines(cr=0):
                m = self.regex.match(line)
                if m:
                    return m.group(2)

    def write_default(self, indexserver):
        if self.path.exists():
            raise ValueError("config file already exists")
        content = "\n".join([self.section_name,
                             "%s = %s\n" % (self.config_name, indexserver)])
        self.path.ensure().write(content)

    def write_indexserver(self, indexserver):
        self.ensure_backup_file()
        if not self.path.exists():
            self.write_default(indexserver)
        else:
            if self.indexserver:
                section = None
            else:
                section = self.section_name
            newlines = []
            found = False
            for line in self.path.readlines(cr=1):
                if not section:
                    m = self.regex.match(line)
                    if m:
                        line = "%s = %s\n" % (m.group(1), indexserver)
                        found = True
                else:
                    if section in line.lower():
                        line = line + "%s = %s\n" %(
                                                self.config_name, indexserver)
                        found = True
                newlines.append(line)
            if not found:
                newlines.append(self.section_name + "\n")
                newlines.append("%s = %s\n" %(self.config_name, indexserver))
            self.path.write("".join(newlines))

    def ensure_backup_file(self):
        if self.path.exists() and not self.backup_path.exists():
             self.path.copy(self.backup_path)

class DistutilsCfg(BaseCfg):
    section_name = "[easy_install]"
    default_location = ("~/.pydistutils.cfg" if sys.platform != "win32"
                        else "~/pydistutils.cfg")

class PipCfg(BaseCfg):
    section_name = "[global]"
    default_location = ("~/.pip/pip.conf" if sys.platform != "win32"
                        else "~/pip/pip.ini")


def parse_keyvalue_spec(keyvaluelist, keyset=None):
    d = {}
    for x in keyvaluelist:
        key, val = x.split("=", 1)
        if keyset and key not in keyset:
            raise KeyError("invalid key: %s, allowed: %s" % (key, keyset))
        d[key] = val
    return d
