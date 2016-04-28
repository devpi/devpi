from copy import deepcopy
import os
import sys
import py
import re

import json

from devpi_common.url import URL

if sys.platform == "win32":
    vbin = "Scripts"
else:
    vbin = "bin"

devpi_endpoints = "index simpleindex pypisubmit login".split()

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
    venvdir = currentproperty("venvdir")
    _auth = currentproperty("auth")
    _basic_auth = currentproperty("basic_auth")
    _client_cert = currentproperty("client_cert")
    always_setcfg = currentproperty("always_setcfg")

    def __init__(self):
        self._currentdict = {}

    @property
    def simpleindex_auth(self):
        indexserver = URL(self.simpleindex)
        basic_auth = self.get_basic_auth(indexserver)
        if basic_auth:
            indexserver = indexserver.replace(netloc="%s@%s" % (
                ':'.join(basic_auth), indexserver.netloc))
        return indexserver.url

    @property
    def searchindex_auth(self):
        indexserver = self.get_index_url()
        basic_auth = self.get_basic_auth(indexserver)
        if basic_auth:
            indexserver = indexserver.replace(netloc="%s@%s" % (
                ':'.join(basic_auth), indexserver.netloc))
        return indexserver.url

    @property
    def index_url(self):
        if self.index:
            return URL(self.index)
        return URL("")

    def _value_from_dict_by_url(self, d, url, default=None):
        # searches for longest match, so there can be multiple devpi instances
        # on the same domain with different paths
        url = URL(url)
        while url:
            if url in d or url.path == '/':
                break
            url = url.joinpath('..')
        return d.get(url.url, default)

    def _get_auth_dict(self):
        auth = self._auth
        if not isinstance(auth, dict):
            auth = {}
        return auth

    def set_auth(self, user, password):
        auth = self._get_auth_dict()
        auth[self.rooturl] = (user, password)
        self.reconfigure(data=dict(_auth=auth))

    def del_auth(self):
        auth = self._get_auth_dict()
        try:
            del auth[self.rooturl]
        except KeyError:
            return False
        self.reconfigure(data=dict(_auth=auth))
        return True

    def get_auth_user(self):
        return self._get_auth_dict().get(self.rooturl, [None])[0]

    def get_auth(self, url=None):
        url = url if url is not None else self.rooturl
        auth = self._value_from_dict_by_url(self._get_auth_dict(), url)
        return tuple(auth) if auth else None

    def _get_basic_auth_dict(self):
        basic_auth = self._basic_auth
        if not isinstance(basic_auth, dict):
            basic_auth = {}
        return basic_auth

    def _get_normalized_url(self, url):
        # returns url with port always included
        url = URL(url)
        if ':' not in url.netloc:
            if url.scheme == 'http':
                url = url.replace(netloc="%s:80" % url.netloc)
            elif url.scheme == 'https':
                url = url.replace(netloc="%s:443" % url.netloc)
        return url.url

    def set_basic_auth(self, user, password):
        # store at root_url, so we can find it from any sub path
        url = self._get_normalized_url(self.root_url)
        basic_auth = self._get_basic_auth_dict()
        basic_auth[url] = (user, password)
        self.reconfigure(data=dict(_basic_auth=basic_auth))

    def get_basic_auth(self, url=None):
        url = self._get_normalized_url(url)
        basic_auth = self._value_from_dict_by_url(
            self._get_basic_auth_dict(), url)
        return tuple(basic_auth) if basic_auth else None

    def _get_client_cert_dict(self):
        client_cert = self._client_cert
        if not isinstance(client_cert, dict):
            client_cert = {}
        return client_cert

    def set_client_cert(self, cert):
        # store at root_url, so we can find it from any sub path
        url = self._get_normalized_url(self.root_url)
        client_cert = self._get_client_cert_dict()
        client_cert[url] = cert
        self.reconfigure(data=dict(_client_cert=client_cert))

    def del_client_cert(self, url=None):
        # stored at root_url, so we can find it from any sub path
        url = self._get_normalized_url(self.root_url)
        client_cert = self._get_client_cert_dict()
        try:
            del client_cert[url]
        except KeyError:
            return False
        self.reconfigure(data=dict(_client_cert=client_cert))
        return True

    def get_client_cert(self, url=None):
        url = self._get_normalized_url(url)
        client_cert = self._value_from_dict_by_url(
            self._get_client_cert_dict(), url)
        return client_cert if client_cert else None

    def reconfigure(self, data):
        for name in data:
            oldval = getattr(self, name)
            newval = data[name]
            if oldval != newval:
                setattr(self, name, newval)

    def exists(self):
        return self.path and self.path.check()

    def _normalize_url(self, url):
        url = URL(url, asdir=1)
        if not url.is_valid_http_url():
            url = URL(self.simpleindex, url.url).url
        return url

    def switch_to_temporary(self, hub, url):
        current = Current()
        current._currentdict = deepcopy(self._currentdict)
        current.configure_fromurl(hub, url)
        return current

    def configure_fromurl(self, hub, url, client_cert=None):
        is_absolute_url = url is not None and '://' in url
        url = self.get_index_url(url)
        if not url.is_valid_http_url():
            hub.fatal("invalid URL: %s" % url.url)
        basic_auth = None
        if '@' in url.netloc:
            basic_auth, netloc = url.netloc.rsplit('@', 1)
            if ':' not in basic_auth:
                hub.fatal("When using basic auth, you have to provide username and password.")
            basic_auth = tuple(basic_auth.split(':', 1))
            url = url.replace(netloc=netloc)
            hub.info("Using basic authentication for '%s'." % url.url)
            hub.warn("The password is stored unencrypted!")
        elif is_absolute_url:
            if self.get_basic_auth(url=url) is not None:
                hub.info("Using existing basic auth for '%s'." % url)
                hub.warn("The password is stored unencrypted!")
        if client_cert:
            client_cert = os.path.abspath(os.path.expanduser(client_cert))
            if not os.path.exists(client_cert):
                hub.fatal("The client certificate at '%s' doesn't exist.")
        elif self.get_client_cert(url=url) is not None:
            hub.info("Using existing client cert for '%s'." % url.url)
        r = hub.http_api(
            "get", url.addpath("+api"), quiet=True,
            auth=self.get_auth(url=url),
            basic_auth=basic_auth or self.get_basic_auth(url=url),
            cert=client_cert or self.get_client_cert(url=url))
        self._configure_from_server_api(r.result, url)
        # at this point we know the root url to store the following data
        if basic_auth is not None:
            self.set_basic_auth(basic_auth[0], basic_auth[1])
        if client_cert is not None:
            if client_cert:
                self.set_client_cert(client_cert)
            else:
                hub.warn("Removing stored client cert for '%s'." % url.url)
                self.del_client_cert(url=url)

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
            self.del_auth()

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
            return self.root_url.url

    @property
    def root_url(self):
        if self.login:
            return URL(self.login, ".")

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

    def get_project_url(self, name, indexname=None):
        return self.get_index_url(indexname=indexname).addpath(name, asdir=1)

    def get_simpleindex_url(self, indexname=None):
        return self.get_index_url(
            indexname=indexname).addpath('+simple', asdir=1)

    def get_simpleproject_url(self, name, indexname=None):
        return self.get_simpleindex_url(
            indexname=indexname).addpath(name, asdir=1)


class PersistentCurrent(Current):
    def __init__(self, path):
        Current.__init__(self)
        self.path = path
        if self.path.check():
            self._currentdict.update(json.loads(self.path.read()))

    def reconfigure(self, data):
        Current.reconfigure(self, data)
        try:
            olddata = json.loads(self.path.read())
        except Exception:
            olddata = {}
        if self._currentdict != olddata:
            oldumask = os.umask(7 * 8 + 7)
            try:
                self.path.write(
                    json.dumps(self._currentdict, indent=2, sort_keys=True))
            finally:
                os.umask(oldumask)


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

    url = None
    if args.url:
        url = args.url
    if url or current.index:
        current.configure_fromurl(hub, url, client_cert=args.client_cert)

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
            indexserver = hub.current.simpleindex_auth
            searchindexserver = hub.current.searchindex_auth
            DistutilsCfg().write_indexserver(indexserver)
            PipCfg().write_indexserver(indexserver)
            PipCfg().write_searchindexserver(searchindexserver)
            BuildoutCfg().write_indexserver(indexserver)

    show_one_conf(hub, DistutilsCfg())
    show_one_conf(hub, PipCfg())
    show_one_conf(hub, BuildoutCfg())
    hub.line("always-set-cfg: %s" % ("yes" if hub.current.always_setcfg else
                                     "no"))

def show_one_conf(hub, cfg):
    if not cfg.exists():
        status = "no config file exists"
    elif not cfg.indexserver:
        status = "no index server configured"
    else:
        status = cfg.indexserver
    hub.info("%-23s: %s" %(cfg.screen_name, status))

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

    @property
    def default_location(self):
        default_location = ("~/.pip/pip.conf" if sys.platform != "win32"
                            else "~/pip/pip.ini")
        return os.environ.get('PIP_CONFIG_FILE', default_location)

    def write_searchindexserver(self, searchindexserver):
        self.ensure_backup_file()
        if not self.path.exists():
            return
        section = '[search]'
        newlines = []
        found = False
        insection = False
        for line in self.path.readlines(cr=1):
            if insection:
                if line.strip().startswith('['):
                    insection = False
            if section in line.lower() and not insection:
                insection = True
            if insection and re.match('index\s*=.*', line):
                line = "index = %s\n" % searchindexserver
                found = True
            newlines.append(line)
        if not found:
            newlines.append(section + "\n")
            newlines.append("index = %s\n" % searchindexserver)
        self.path.write("".join(newlines))


class BuildoutCfg(BaseCfg):
    section_name = "[buildout]"
    config_name = "index"
    regex = re.compile(r"(index)\s*=\s*(.*)")
    default_location = "~/.buildout/default.cfg"


def parse_keyvalue_spec(keyvaluelist, keyset=None):
    d = {}
    for x in keyvaluelist:
        key, val = x.split("=", 1)
        if keyset and key not in keyset:
            raise KeyError("invalid key: %s, allowed: %s" % (key, keyset))
        d[key] = val
    return d
