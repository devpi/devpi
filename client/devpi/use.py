from copy import deepcopy
from operator import attrgetter
from urllib.parse import quote as url_quote
import itertools
import os
import sys
import re
import json
import shutil

from devpi_common.types import cached_property
from devpi_common.url import URL
from pathlib import Path


if sys.platform == "win32":
    vbin = "Scripts"
else:
    vbin = "bin"

devpi_endpoints = "index simpleindex pypisubmit login".split()
devpi_data_keys = ["features"]


class baseproperty(object):
    def __init__(self, name):
        self.name = name

    def __get__(self, inst, owner=None):
        if inst is None:
            return self
        return getattr(inst, self.dict_name).get(self.name)

    def __set__(self, inst, value):
        getattr(inst, self.dict_name)[self.name] = value


class authproperty(baseproperty):
    dict_name = '_authdict'


class currentproperty(baseproperty):
    dict_name = '_currentdict'


class indexproperty(baseproperty):
    dict_name = '_currentdict'


class Current(object):
    index = indexproperty("index")
    simpleindex = indexproperty("simpleindex")
    pypisubmit = indexproperty("pypisubmit")
    login = indexproperty("login")
    username = currentproperty("username")
    venvdir = currentproperty("venvdir")
    _auth = authproperty("auth")
    _basic_auth = authproperty("basic_auth")
    _client_cert = authproperty("client_cert")
    always_setcfg = currentproperty("always_setcfg")
    settrusted = currentproperty("settrusted")
    features = currentproperty("features")

    def __init__(self):
        self._authdict = {}
        self._currentdict = {}

    @property
    def simpleindex_auth(self):
        indexserver = URL(self.simpleindex)
        basic_auth = self.get_basic_auth(indexserver)
        if basic_auth:
            (username, password) = basic_auth
            indexserver = indexserver.replace(
                username=url_quote(username), password=url_quote(password))
        return indexserver.url

    @property
    def searchindex_auth(self):
        indexserver = self.get_index_url()
        basic_auth = self.get_basic_auth(indexserver)
        if basic_auth:
            (username, password) = basic_auth
            indexserver = indexserver.replace(
                username=url_quote(username), password=url_quote(password))
        return indexserver.url

    @property
    def indexname(self):
        return self.index[len(self.root_url.url):]

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
        rooturl = self.root_url.url
        auth_users = dict(auth.get(rooturl, []))
        auth_users.pop(user, None)
        auth[rooturl] = list(itertools.chain(
            [(user, password)], sorted(auth_users.items())))
        self.username = user
        self.reconfigure(data=dict(_auth=auth))

    def del_auth(self):
        user = self.get_auth_user()
        auth = self._get_auth_dict()
        rooturl = self.root_url.url
        auth_users = dict(auth.get(rooturl, []))
        if user not in auth_users:
            return False
        del auth_users[user]
        auth[rooturl] = sorted(auth_users.items())
        self.reconfigure(data=dict(_auth=auth))
        return True

    def get_auth_user(self, username=None):
        if "DEVPI_USER" in os.environ:
            username = os.environ["DEVPI_USER"]
        if username is None:
            username = self.username
        if username is None:
            auth = self._value_from_dict_by_url(self._get_auth_dict(), self.root_url)
            if auth:
                username = auth[0][0]
        auth = self.get_auth(username=username)
        if auth is None:
            return
        return username

    def get_auth(self, url=None, username=None):
        url = url if url is not None else self.root_url
        username = username if username is not None else self.username
        auth = self._value_from_dict_by_url(self._get_auth_dict(), url)
        if not auth:
            return
        auth = dict(auth)
        auth = auth.get(username)
        return (username, auth) if auth is not None else None

    def add_auth_to_url(self, url):
        url = URL(url)
        auth = self.get_auth()
        if auth is not None:
            url = url.replace(
                username=url_quote(auth[0]), password=url_quote(auth[1]))
        return url

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
        return False

    def _normalize_url(self, url):
        url = URL(url, asdir=1)
        if not url.is_valid_http_url():
            url = URL(self.simpleindex, url.url).url
        return url

    def switch_to_local(self, hub, url, current_path):
        current = PersistentCurrent(self.auth_path, current_path)
        current._authdict = self._authdict
        current._currentdict = deepcopy(self._currentdict)
        # we make sure to remove legacy auth data
        current._currentdict.pop("auth", None)
        if url is not None:
            current.configure_fromurl(hub, url)
        return current

    def switch_to_temporary(self, hub, url):
        current = Current()
        current._authdict = deepcopy(self._authdict)
        current._currentdict = deepcopy(self._currentdict)
        current.configure_fromurl(hub, url)
        return current

    def configure_fromurl(self, hub, url, client_cert=None):
        is_absolute_url = url is not None and '://' in url
        url = self.get_index_url(url)
        if not url.is_valid_http_url():
            hub.fatal("invalid URL: %s" % url.url)
        try:
            # if the server is on http and not localhost, pip will show verbose warning
            # every time you use devpi. set-trusted instead and inform user now just the once
            if (
                    hub.args.settrusted == 'auto'
                    and url.scheme == 'http'
                    and url.hostname not in ('localhost', '127.0.0.0')):
                hub.line("Warning: insecure http host, trusted-host will be set for pip")
                hub.args.settrusted = 'yes'
        except AttributeError:
            pass  # Ignore for usages where hub.args.settrusted doesn't exist
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
                hub.fatal("The client certificate at '%s' doesn't exist." % client_cert)
        elif self.get_client_cert(url=url) is not None:
            hub.info("Using existing client cert for '%s'." % url.url)

        def call_http_api(verify):
            r = hub.http_api(
                "get", url.addpath("+api"), quiet=True,
                auth=self.get_auth(url=url),
                fatal=False,
                basic_auth=basic_auth or self.get_basic_auth(url=url),
                cert=client_cert or self.get_client_cert(url=url),
                verify=verify)
            if r.status_code == 403:
                r = hub.http_api(
                    "get", url.addpath("+api"), quiet=True,
                    basic_auth=basic_auth or self.get_basic_auth(url=url),
                    cert=client_cert or self.get_client_cert(url=url),
                    verify=verify)
            return r
        try:
            # Try calling http_api with ssl verification active
            r = call_http_api(verify=True)
        except hub.http.SSLError:
            # SSL certificate validation failed, set-trusted will be needed
            hub.args.settrusted = 'yes'
            # re-run http_api call ignoring the failed verification
            r = call_http_api(verify=False)
            hub.line("Warning: https certificate validation failed (self signed?), trusted-host will be set for pip")
        self._configure_from_server_api(r.result, url)
        # at this point we know the root url to store the following data
        if basic_auth is not None:
            hub.warn(
                "Use of basic authentication is deprecated, "
                "take a look at devpi-lockdown instead. "
                "If that doesn't work for you, "
                "let us know by filing an issue with details of your usecase.")
            self.set_basic_auth(basic_auth[0], basic_auth[1])
        if client_cert is not None:
            if client_cert:
                hub.warn(
                    "Use of client side certificates is deprecated, "
                    "take a look at devpi-lockdown instead. "
                    "If that doesn't work for you, "
                    "let us know by filing an issue with details of your usecase.")
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
        for name in devpi_data_keys:
            val = result.get(name, None)
            data[name] = val
        self.reconfigure(data)
        status = result.get("authstatus", None)
        if status and status[0] not in ["ok", "noauth"]:
            self.del_auth()

    def getvenvbin(self, name, venvdir=None, glob=True):
        if venvdir is None:
            venvdir = self.venvdir
        if venvdir:
            bindir = Path(venvdir) / vbin
            return shutil.which(name, path=str(bindir))
        if glob:
            return shutil.which(name)

    @property
    def root_url(self):
        if self.login:
            return URL(self.login, ".")
        return URL()

    def get_user_url(self, user=None):
        if user is None:
            user = self.get_auth_user()
            if not user:
                raise ValueError("no current authenticated user")
        if '/' in user:
            raise ValueError("user name contains a slash")
        return self.root_url.addpath(user)

    def get_index_url(self, indexname=None, slash=True):
        if indexname is None:
            indexname = self.index
            if indexname is None:
                raise ValueError("no index name")
        if "/" not in indexname:
            return self.get_user_url().addpath(indexname)
        if not slash:
            indexname = indexname.rstrip("/")
        return self.root_url.joinpath(indexname, asdir=slash)

    def get_project_url(self, name, indexname=None):
        return self.get_index_url(indexname=indexname).addpath(name, asdir=1)

    def get_simpleindex_url(self, indexname=None):
        return self.get_index_url(
            indexname=indexname).addpath('+simple', asdir=1)

    def get_simpleproject_url(self, name, indexname=None):
        return self.get_simpleindex_url(
            indexname=indexname).addpath(name, asdir=1)


def _load_json(path, dest):
    if path is None:
        return
    path = Path(path)
    if not path.is_file():
        return
    raw = path.read_text().strip()
    if not raw:
        return
    data = json.loads(raw)
    if not isinstance(data, dict):
        return
    dest.update(data)


class PersistentCurrent(Current):
    persist_index = True

    def __init__(self, auth_path, current_path):
        Current.__init__(self)
        self.auth_path = auth_path
        self.current_path = current_path
        _load_json(self.auth_path, self._authdict)
        _load_json(self.current_path, self._currentdict)

    def exists(self):
        return self.current_path and self.current_path.is_file()

    def _persist(self, data, path, force_write=False):
        if path is None:
            return
        path = Path(path)
        try:
            olddata = json.loads(path.read_text())
        except Exception:
            olddata = {}
        if force_write or data != olddata:
            oldumask = os.umask(7 * 8 + 7)
            try:
                path.write_text(
                    json.dumps(data, indent=2, sort_keys=True))
            finally:
                os.umask(oldumask)

    def reconfigure(self, data, force_write=False):
        Current.reconfigure(self, data)
        self._persist(self._authdict, self.auth_path, force_write=force_write)
        currentdict = {}
        _load_json(self.current_path, currentdict)
        for key, value in self._currentdict.items():
            prop = getattr(self.__class__, key, None)
            if isinstance(prop, indexproperty) and not self.persist_index:
                continue
            currentdict[key] = value
        # we make sure to remove legacy auth data
        currentdict.pop("auth", None)
        self._persist(currentdict, self.current_path, force_write=force_write)


def out_index_list(hub, data):
    for user in sorted(data):
        indexes = data[user].get("indexes", {})
        for index, ixconfig in sorted(indexes.items()):
            ixname = "%s/%s" % (user, index)
            hub.info("%-15s bases=%-15s volatile=%s" %(ixname,
                     ",".join(ixconfig.get("bases", [])),
                     ixconfig["volatile"]))


def main(hub, args=None):
    args = hub.args
    if args.local:
        if hub.local_current_path is None:
            hub.fatal("Using --local is only valid in an active virtualenv.")
        if not hub.local_current_path.exists():
            current = hub.current
            hub.info("Creating local configuration at %s" % hub.local_current_path)
            hub.local_current_path.touch()
            current = current.switch_to_local(
                hub, current.index, hub.local_current_path)
            # now store existing data in new location
            current.reconfigure({}, force_write=True)
    current = hub.get_current(args.url)

    if args.delete:
        if not hub.current.exists():
            hub.error_and_out("NO configuration found")
        hub.current.current_path.unlink()
        hub.info("REMOVED configuration at", hub.current.current_path)
        return
    if current.exists():
        hub.debug("current: %s" % current.current_path)
    else:
        hub.debug("no current file, using defaults")

    url = None
    if args.url:
        url = args.url
        if args.list or args.urls:
            current = hub.current.switch_to_temporary(hub, url)
    if url or current.index:
        current.configure_fromurl(hub, url, client_cert=args.client_cert)
        url_parts = attrgetter('scheme', 'hostname', 'port')(URL(url))
        if url_parts[0]:
            # only check if a full url was used
            new_url = current.index_url if current.index else current.root_url
            new_parts = attrgetter('scheme', 'hostname', 'port')(new_url)
            for url_part, new_part in zip(url_parts, new_parts):
                if url_part != new_part:
                    hub.warn(
                        "The server has rewritten the url to: %s" % new_url)
                    break

    if args.list:
        rooturl = current.root_url
        if not rooturl:
            hub.fatal("not connected to any server")
        if args.user:
            rooturl = rooturl.joinpath(args.user)
        r = hub.http_api("GET", rooturl, {}, quiet=True)
        result = r.result
        if args.user:
            result = {args.user: result}
        out_index_list(hub, result)
        return 0

    showurls = args.urls or args.debug

    user = current.get_auth_user(args.user)
    if user:
        if args.user and user != current.username:
            current.reconfigure(dict(username=user))
        r = hub.http_api("GET", current.root_url.joinpath("+api"))
        if r.status_code == 200:
            authstatus = r.json().get("result", {}).get("authstatus")
            if authstatus and authstatus[0] != "ok":
                # update login status
                current.del_auth()
                user = None
    if user:
        login_status = "logged in as %s" % user
    else:
        login_status = "not logged in"
    if current.root_url:
        if current.index:
            hub.info("current devpi index: %s (%s)" % (current.index, login_status))
            if showurls:
                for name in devpi_endpoints:
                    if name == 'index':
                        continue
                    hub.info("%19s: %s" %(name, getattr(current, name)))
            if current.features:
                hub.info("supported features: %s" % ", ".join(sorted(current.features)))
            hub.validate_index_access()
        else:
            hub.info("using server: %s (%s)" % (current.root_url, login_status))
            hub.error("no current index: type 'devpi use -l' "
                      "to discover indices")
    else:
        hub.line("no server: type 'devpi use URL' with a URL "
                 "pointing to a server or directly to an index.")

    venvdir = hub.venv
    if venvdir:
        hub.info("venv for install/set commands: %s" % venvdir)

    settrusted = hub.args.settrusted == 'yes'
    if hub.args.always_setcfg:
        always_setcfg = hub.args.always_setcfg == "yes"
        current.reconfigure(dict(
            always_setcfg=always_setcfg, settrusted=settrusted))
    pipcfg = PipCfg(venv=venvdir)
    if pipcfg.legacy_location == pipcfg.default_location:
        hub.warn(
            "Detected pip config at legacy location: %s\n"
            "You should move it to: %s" % (
                pipcfg.legacy_location, pipcfg.new_location))

    if venvdir:
        hub.line("only setting venv pip cfg, no global configuration changed")
        extra_cfgs = []
    else:
        extra_cfgs = [DistutilsCfg(), BuildoutCfg()]

    if hub.args.setcfg or current.always_setcfg:
        if not hub.current.index:
            hub.error("no index configured: cannot set pip/easy_install index")
        else:
            indexserver = current.simpleindex_auth
            searchindexserver = current.searchindex_auth
            for cfg in extra_cfgs:
                cfg.write_indexserver(indexserver)

            pipcfg.write_indexserver(indexserver)
            pipcfg.write_searchindexserver(searchindexserver)
            if settrusted or hub.current.settrusted:
                pipcfg.write_trustedhost(indexserver)
            else:
                pipcfg.clear_trustedhost(indexserver)

            extra_cfgs.append(pipcfg)
    for cfg in [pipcfg] + extra_cfgs:
        show_one_conf(hub, cfg)
    hub.line("always-set-cfg: %s" % ("yes" if current.always_setcfg else "no"))


def show_one_conf(hub, cfg):
    if not cfg.exists():
        status = "no config file exists"
    elif not cfg.indexserver:
        status = "no index server configured"
    else:
        url = URL(cfg.indexserver)
        if url.password:
            url = url.replace(password="****")  # noqa: S106
        status = url.url
    hub.info("%s: %s" % (cfg.screen_name, status))


class BaseCfg(object):
    config_name = "index_url"
    regex = re.compile(r"(index[_-]url)\s*=\s*(.*)")

    def __init__(self, path=None):
        if path is None:
            path = self.default_location
        self.screen_name = str(path)
        self.path = Path(path).expanduser()
        self.backup_path = self.path.with_name(self.path.name + "-bak")

    def exists(self):
        return self.path.exists()

    @property
    def indexserver(self):
        if not self.path.exists():
            return
        with self.path.open() as f:
            for line in f:
                m = self.regex.match(line)
                if m:
                    return m.group(2)

    def write_default(self, indexserver):
        if self.path.exists():
            raise ValueError("config file already exists")
        content = "\n".join([self.section_name,
                             "%s = %s\n" % (self.config_name, indexserver)])
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(content)

    def write_indexserver(self, indexserver):
        self.ensure_backup_file()
        if not self.path.exists():
            self.write_default(indexserver)
            return
        if self.indexserver:
            section = None
        else:
            section = self.section_name
        newlines = []
        found = False
        with self.path.open() as f:
            for line in f:
                if not section:
                    m = self.regex.match(line)
                    if m:
                        line = "%s = %s\n" % (m.group(1), indexserver)
                        found = True
                elif section in line.lower():
                    line = line + "%s = %s\n" % (self.config_name, indexserver)
                    found = True
                newlines.append(line)
            if not found:
                newlines.append(self.section_name + "\n")
                newlines.append("%s = %s\n" %(self.config_name, indexserver))
        self.path.write_text("".join(newlines))

    def ensure_backup_file(self):
        if self.path.exists() and not self.backup_path.exists():
            self.backup_path.write_text(self.path.read_text())
            shutil.copyfile(self.path, self.backup_path)


class DistutilsCfg(BaseCfg):
    section_name = "[easy_install]"
    default_location = Path(
        "~/.pydistutils.cfg"
        if sys.platform != "win32"
        else "~/pydistutils.cfg").expanduser()


class PipCfg(BaseCfg):
    section_name = "[global]"

    def __init__(self, path=None, venv=None):
        self.venv = venv
        super(PipCfg, self).__init__(path=path)

    @cached_property
    def appdirs(self):
        # try to get the vendored appdirs from pip to get same behaviour
        try:
            from pip._internal.utils import appdirs
        except ImportError:
            import platformdirs as appdirs
        return appdirs

    @property
    def legacy_location(self):
        confdir = Path(
            "~/.pip" if sys.platform != "win32" else "~/pip").expanduser()
        return confdir / self.pip_conf_name

    @property
    def new_location(self):
        return Path(
            self.appdirs.user_config_dir("pip")) / self.pip_conf_name

    @property
    def default_location(self):
        if self.venv:
            default_location = Path(
                self.venv).expanduser() / self.pip_conf_name
        elif 'PIP_CONFIG_FILE' in os.environ:
            default_location = os.environ.get('PIP_CONFIG_FILE')
        elif self.legacy_location.exists():
            default_location = self.legacy_location
        else:
            default_location = self.new_location
        return default_location

    @property
    def pip_conf_name(self):
        return "pip.conf" if sys.platform != "win32" else "pip.ini"

    def write_searchindexserver(self, searchindexserver):
        self.ensure_backup_file()
        if not self.path.exists():
            return
        section = '[search]'
        newlines = []
        found = False
        insection = False
        with self.path.open() as f:
            for line in f:
                if insection:
                    if line.strip().startswith('['):
                        insection = False
                if section in line.lower() and not insection:
                    insection = True
                if insection and re.match(r'index\s*=.*', line):
                    line = "index = %s\n" % searchindexserver
                    found = True
                newlines.append(line)
        if not found:
            newlines.append(section + "\n")
            newlines.append("index = %s\n" % searchindexserver)
        self.path.write_text("".join(newlines))

    def write_trustedhost(self, indexserver):
        self.ensure_backup_file()
        if not self.path.exists():
            return
        newlines = []
        found = False
        insection = False
        indexserver = URL(indexserver)
        trustedhost = "trusted-host = %s\n" % indexserver.hostname
        with self.path.open() as f:
            for line in f:
                if insection:
                    if line.strip().startswith('['):
                        if not found:
                            newlines.append(trustedhost)
                            found = True
                        insection = False
                if not found and self.section_name in line.lower() and not insection:
                    insection = True
                if not found and insection and re.match(r'trusted-host\s*=\s*%s' % indexserver.hostname, line):
                    found = True
                newlines.append(line)
        if not found:
            newlines.append(self.section_name + "\n")
            newlines.append(trustedhost)
        self.path.write_text("".join(newlines))

    def clear_trustedhost(self, indexserver):
        self.ensure_backup_file()
        if not self.path.exists():
            return
        newlines = []
        indexserver = URL(indexserver)
        with self.path.open() as f:
            for line in f:
                if not re.match(r'trusted-host\s*=\s*%s' % indexserver.hostname, line):
                    newlines.append(line)
        self.path.write_text("".join(newlines))


class BuildoutCfg(BaseCfg):
    section_name = "[buildout]"
    config_name = "index"
    regex = re.compile(r"(index)\s*=\s*(.*)")
    default_location = Path("~/.buildout/default.cfg").expanduser()


class KeyValues(list):
    @property
    def kvdict(self):
        kvdict = {}
        for keyvalue in self:
            key, value = keyvalue.split("=", 1)
            kvdict[key] = value
        return kvdict


def get_keyvalues(keyvaluelist):
    for keyvalue in keyvaluelist:
        if '=' not in keyvalue:
            raise ValueError('No equal sign in argument')
    return KeyValues(keyvaluelist)
