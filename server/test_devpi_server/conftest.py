import re
from webtest.forms import Upload
import json
import webtest
import mimetypes
import subprocess

import pytest
import py
import requests
import socket
import sys
import time
from .reqmock import reqmock, patch_reqsessionmock  # noqa
from bs4 import BeautifulSoup
from contextlib import closing
from devpi_server import mirror
from devpi_server.config import get_pluginmanager
from devpi_server.main import XOM, parseoptions
from devpi_common.validation import normalize_name
from devpi_common.url import URL
from devpi_server.log import threadlog, thread_clear_log
from io import BytesIO
from pyramid.authentication import b64encode
from pyramid.httpexceptions import status_map
from queue import Queue as BaseQueue
import hashlib


@pytest.fixture(scope="session")
def server_version():
    from devpi_server import __version__
    from devpi_common.metadata import parse_version
    return parse_version(__version__)


def make_file_url(basename, content, stagename=None, baseurl="http://localhost/", add_hash=True):
    from devpi_server.filestore import get_default_hash_spec, make_splitdir
    hash_spec = get_default_hash_spec(content)
    hashdir = "/".join(make_splitdir(hash_spec))
    if add_hash:
        s = "%s{stage}/+f/%s/%s#%s" % (baseurl, hashdir, basename, hash_spec)
    else:
        s = "%s{stage}/+f/%s/%s" % (baseurl, hashdir, basename)
    if stagename is not None:
        s = s.format(stage=stagename)
    return s


class _TimeoutQueue(BaseQueue):
    def get(self, timeout=2):
        return BaseQueue.get(self, timeout=timeout)


log = threadlog


@pytest.fixture(autouse=True)
def _clear():
    thread_clear_log()


LOWER_ARGON2_MEMORY_COST = 8
LOWER_ARGON2_PARALLELISM = 1
LOWER_ARGON2_TIME_COST = 1


@pytest.fixture(autouse=True)
def lower_argon2_parameters(monkeypatch):
    from devpi_server.config import Config
    import argon2

    secret_parameters = argon2.Parameters(
        type=argon2.low_level.Type.ID,
        version=argon2.low_level.ARGON2_VERSION,
        salt_len=16,
        hash_len=16,
        time_cost=LOWER_ARGON2_TIME_COST,
        memory_cost=LOWER_ARGON2_MEMORY_COST,
        parallelism=LOWER_ARGON2_PARALLELISM)

    monkeypatch.setattr(
        Config, "_secret_parameters", secret_parameters)


@pytest.fixture
def TimeoutQueue():
    return _TimeoutQueue


@pytest.fixture()
def caplog(caplog):
    import logging
    """ enrich the pytest-catchlog funcarg. """
    def getrecords(msgrex=None, minlevel="DEBUG"):
        if msgrex is not None:
            msgrex = re.compile(msgrex, re.DOTALL)
        minlevelno = {"DEBUG": 10, "INFO": 20, "WARNING": 30,
                      "ERROR": 40, "FATAL": 50}.get(minlevel)
        recs = []
        for rec in caplog.records:
            if rec.levelno < minlevelno:
                continue
            if msgrex is not None and not msgrex.search(rec.getMessage()):
                continue
            recs.append(rec)
        return recs
    caplog.getrecords = getrecords
    caplog.set_level(logging.NOTSET)
    return caplog


@pytest.fixture
def gentmp(request, tmpdir_factory):
    cache = []

    def gentmp(name=None):
        if not cache:
            prefix = re.sub(r"[\W]", "_", request.node.name)
            basedir = tmpdir_factory.mktemp(prefix, numbered=True)
            cache.append(basedir)
        else:
            basedir = cache[0]
        if name:
            return basedir.mkdir(name)
        return py.path.local.make_numbered_dir(prefix="gentmp",
                keep=0, rootdir=basedir, lock_timeout=None)

    return gentmp


@pytest.fixture(autouse=True)
def auto_transact(request):
    names = request.fixturenames
    if ("xom" not in names and "keyfs" not in names) or (
            request.node.get_closest_marker("notransaction")):
        yield
        return
    keyfs = request.getfixturevalue("keyfs")

    write = True if request.node.get_closest_marker("writetransaction") else False
    keyfs.begin_transaction_in_thread(write=write)
    yield
    try:
        keyfs.rollback_transaction_in_thread()
    except AttributeError:  # already finished within the test
        pass


@pytest.fixture
def xom(request, makexom):
    xom = makexom([])
    request.addfinalizer(xom.keyfs.release_all_wait_tx)
    return xom


def _speed_up_sqlite(cls):
    old = cls.ensure_tables_exist

    def make_unsynchronous(self, old=old):
        conn = old(self)
        with self.get_connection() as conn:
            conn._sqlconn.execute("PRAGMA synchronous=OFF")
        return

    cls.ensure_tables_exist = make_unsynchronous
    return old


@pytest.fixture(autouse=True, scope="session")
def speed_up_sqlite():
    from devpi_server.keyfs_sqlite import Storage
    old = _speed_up_sqlite(Storage)
    yield
    Storage.ensure_tables_exist = old


@pytest.fixture(autouse=True, scope="session")
def speed_up_sqlite_fs():
    from devpi_server.keyfs_sqlite_fs import Storage
    old = _speed_up_sqlite(Storage)
    yield
    Storage.ensure_tables_exist = old


@pytest.fixture(scope="session")
def mock():
    from unittest import mock
    return mock


@pytest.fixture(scope="session")
def storage_info(request):
    from pydoc import locate
    backend = getattr(request.config.option, 'backend', None)
    if backend is None:
        backend = 'devpi_server.keyfs_sqlite_fs'
    plugin = locate(backend)
    if plugin is None:
        raise RuntimeError("Couldn't find storage backend '%s'" % backend)
    result = plugin.devpiserver_storage_backend(settings=None)
    result["_test_plugin"] = plugin
    return result


@pytest.fixture(scope="session")
def storage(storage_info):
    return storage_info['storage']


@pytest.fixture
def makexom(request, gentmp, httpget, monkeypatch, storage_info):
    def makexom(opts=(), httpget=httpget, plugins=()):
        from devpi_server import auth_basic
        from devpi_server import auth_devpi
        from devpi_server import model
        from devpi_server import replica
        from devpi_server import view_auth
        from devpi_server import views
        from devpi_server.interfaces import verify_connection_interface
        plugins = [
            plugin[0] if isinstance(plugin, tuple) else plugin
            for plugin in plugins]
        default_plugins = [
            auth_basic, auth_devpi, mirror, model, replica, view_auth, views,
            storage_info["_test_plugin"]]
        for plugin in default_plugins:
            if plugin not in plugins:
                plugins.append(plugin)
        pm = get_pluginmanager(load_entrypoints=False)
        for plugin in plugins:
            pm.register(plugin)
        serverdir = gentmp()
        if "--serverdir" in opts:
            fullopts = ["devpi-server"] + list(opts)
        else:
            fullopts = ["devpi-server", "--serverdir", serverdir] + list(opts)
        if request.node.get_closest_marker("with_replica_thread"):
            fullopts.append("--master=http://localhost")
        if not request.node.get_closest_marker("no_storage_option"):
            if storage_info["name"] != "sqlite":
                fullopts.append("--storage=%s" % storage_info["name"])
        fullopts = [str(x) for x in fullopts]
        config = parseoptions(pm, fullopts)
        config.init_nodeinfo()
        for marker in ("storage_with_filesystem",):
            if request.node.get_closest_marker(marker):
                info = config._storage_info()
                markers = info.get("_test_markers", [])
                if marker not in markers:
                    pytest.skip("The storage doesn't have marker '%s'." % marker)
        if not request.node.get_closest_marker("no_storage_option"):
            assert storage_info["storage"] is config.storage
        if request.node.get_closest_marker("nomocking"):
            xom = XOM(config)
        else:
            xom = XOM(config, httpget=httpget)
            add_pypistage_mocks(monkeypatch, httpget)
        # verify storage interface
        with xom.keyfs.get_connection() as conn:
            verify_connection_interface(conn)
        # initialize default indexes
        from devpi_server.main import init_default_indexes
        if not xom.config.args.master_url:
            init_default_indexes(xom)
        if xom.is_replica() and request.node.get_closest_marker("with_replica_thread"):
            xom.thread_pool.start_one(xom.replica_thread)
        if request.node.get_closest_marker("start_threads"):
            xom.thread_pool.start()
        elif request.node.get_closest_marker("with_notifier"):
            xom.thread_pool.start_one(xom.keyfs.notifier)
        if not request.node.get_closest_marker("start_threads"):
            # we always need the async_thread
            xom.thread_pool.start_one(xom.async_thread)
        request.addfinalizer(xom.thread_pool.shutdown)
        request.addfinalizer(xom._close_sessions)
        return xom
    return makexom


@pytest.fixture
def replica_xom(request, makexom, secretfile):
    from devpi_server.replica import register_key_subscribers
    master_url = "http://localhost:3111"
    xom = makexom(["--master", master_url, "--secretfile", secretfile.strpath])
    register_key_subscribers(xom)
    return xom


@pytest.fixture
def makefunctionaltestapp(request):
    def makefunctionaltestapp(host_port):
        mt = MyFunctionalTestApp(host_port)
        mt.xom = None
        return mt
    return makefunctionaltestapp


@pytest.fixture
def maketestapp(request):
    def maketestapp(xom):
        app = xom.create_app()
        mt = MyTestApp(app)
        mt.xom = xom
        return mt
    return maketestapp


@pytest.fixture
def makemapp(request, maketestapp, makexom):
    def makemapp(testapp=None, options=()):
        if testapp is None:
            testapp = maketestapp(makexom(options))
        m = Mapp(testapp)
        m.xom = testapp.xom
        return m
    return makemapp


@pytest.fixture
def httpget(pypiurls):
    from .simpypi import make_simple_pkg_info

    class MockHTTPGet:
        def __init__(self):
            self.url2response = {}
            self._md5 = hashlib.md5()
            self.call_log = []

        async def async_httpget(self, url, allow_redirects, timeout=None, extra_headers=None):
            response = self.__call__(url, allow_redirects, extra_headers, timeout=timeout)
            if response.status_code < 300:
                text = response.text
            else:
                text = None
            return (response, text)

        def __call__(self, url, allow_redirects=False, extra_headers=None, **kw):
            class mockresponse:
                def __init__(xself, url):
                    fakeresponse = self.url2response.get(url)
                    if isinstance(fakeresponse, list):
                        if not fakeresponse:
                            pytest.fail(
                                f"http_api call to {url} has no further replies")
                        fakeresponse = fakeresponse.pop(0)
                    if fakeresponse is None:
                        fakeresponse = dict(
                            status_code=404,
                            reason="Not Found")
                    fakeresponse["headers"] = requests.structures.CaseInsensitiveDict(
                        fakeresponse.setdefault("headers", {}))
                    xself.__dict__.update(fakeresponse)
                    if "url" not in fakeresponse:
                        xself.url = url
                    xself.allow_redirects = allow_redirects
                    if "content" in fakeresponse:
                        xself.raw = BytesIO(fakeresponse["content"])
                    xself.headers.setdefault('content-type', fakeresponse.get(
                        'content_type', 'text/html'))
                    if "etag" in fakeresponse:
                        fakeresponse["headers"]["ETag"] = fakeresponse["etag"]

                def close(xself):
                    return

                def json(xself):
                    return json.loads(xself.text)

                @property
                def status(xself):
                    return xself.status_code

                def __repr__(xself):
                    return "<mockresponse %s url=%s>" % (xself.status_code,
                                                         xself.url)
            r = mockresponse(url)
            log.debug("returning %s", r)
            self.call_log.append(dict(
                url=url,
                allow_redirects=allow_redirects,
                extra_headers=extra_headers,
                kw=kw,
                response=r))
            return r

        def _prepare_kw(self, kw):
            kw.setdefault("status_code", kw.pop("code", 200))
            kw.setdefault("reason", getattr(
                status_map.get(kw["status_code"]),
                "title",
                "Devpi Mock Error"))

        def set(self, url, **kw):
            """ Set a reply for all future uses. """
            self._prepare_kw(kw)
            log.debug("set mocking response %s %s", url, kw)
            self.url2response[url] = kw

        def add(self, url, **kw):
            """ Add a one time use reply to the url. """
            self._prepare_kw(kw)
            log.debug("add mocking response %s %s", url, kw)
            self.url2response.setdefault(url, []).append(kw)

        def mockresponse(self, url, **kw):
            self.set(url, **kw)

        def mock_simple(self, name, text="", pkgver=None, hash_type=None,
                        pypiserial=10000, remoteurl=None, requires_python=None,
                        **kw):
            ret, text = make_simple_pkg_info(
                name, text=text, pkgver=pkgver, hash_type=hash_type,
                pypiserial=pypiserial, requires_python=requires_python)
            if remoteurl is None:
                remoteurl = pypiurls.simple
            headers = kw.setdefault("headers", {})
            if pypiserial is not None:
                headers["X-PYPI-LAST-SERIAL"] = str(pypiserial)
            kw.setdefault("url", URL(remoteurl).joinpath(name).asdir().url)
            if "etag" in kw:
                etag = kw.pop("etag")
                self.add(text=text, **kw, etag=etag)
                self.add(text=text, **kw, status_code=304)
            else:
                self.mockresponse(text=text, **kw)
            return ret

        def _getmd5digest(self, s):
            self._md5.update(s.encode("utf8"))
            return self._md5.hexdigest()

    return MockHTTPGet()


@pytest.fixture
def keyfs(xom):
    return xom.keyfs


@pytest.fixture
def model(xom):
    return xom.model


@pytest.fixture
def pypistage(devpiserver_makepypistage, xom):
    return devpiserver_makepypistage(xom)


def add_pypistage_mocks(monkeypatch, httpget):
    _projects = set()

    # add some mocking helpers
    mirror.MirrorStage.url2response = httpget.url2response

    def mock_simple(self, name, text=None, pypiserial=10000, **kw):
        cache_expire = kw.pop("cache_expire", True)
        if cache_expire:
            self.cache_retrieve_times.expire(name)
            self.cache_retrieve_times.release(name)
        add_to_projects = kw.pop("add_to_projects", True)
        if add_to_projects:
            self.mock_simple_projects(
                _projects.union([name]), cache_expire=cache_expire)
        return self.xom.httpget.mock_simple(
            name, text=text, pypiserial=pypiserial, **kw)
    monkeypatch.setattr(
        mirror.MirrorStage, "mock_simple", mock_simple, raising=False)

    def mock_simple_projects(self, projectlist, cache_expire=True):
        if cache_expire:
            self.cache_projectnames.expire()
        _projects.clear()
        _projects.update(projectlist)
        t = "".join(
            '<a href="%s">%s</a>\n' % (normalize_name(name), name)
            for name in projectlist)
        threadlog.debug("patching simple page with: %s" % t)
        self.xom.httpget.mockresponse(self.mirror_url, code=200, text=t)
    monkeypatch.setattr(
        mirror.MirrorStage, "mock_simple_projects",
        mock_simple_projects, raising=False)

    def mock_extfile(self, path, content, **kw):
        headers = {"content-length": len(content),
                   "content-type": mimetypes.guess_type(path),
                   "last-modified": "today",}
        url = URL(self.mirror_url).joinpath(path)
        return self.xom.httpget.mockresponse(
            url.url, content=content, headers=headers, **kw)
    monkeypatch.setattr(
        mirror.MirrorStage, "mock_extfile", mock_extfile, raising=False)


@pytest.fixture
def pypiurls():
    from devpi_server.main import _pypi_ixconfig_default

    class MirrorURL:
        def __init__(self):
            self.simple = _pypi_ixconfig_default['mirror_url']

    return MirrorURL()


@pytest.fixture
def mapp(makemapp, testapp):
    return makemapp(testapp)


from .functional import MappMixin


class Mapp(MappMixin):
    def __init__(self, testapp):
        self.testapp = testapp
        self.current_stage = ""

    def _getindexname(self, indexname):
        if not indexname:
            assert self.current_stage, "no index in use, none specified"
            return self.current_stage
        return indexname

    def _wait_for_serial_in_result(self, r):
        commit_serial = int(r.headers["X-DEVPI-SERIAL"])
        self.xom.keyfs.notifier.wait_event_serial(commit_serial)

    def makepkg(self, basename, content, name, version):
        return content

    def delete_user(self, user, code=200):
        r = self.testapp.delete_json("/%s" % user, expect_errors=True)
        assert r.status_code == code

    def login(self, user="root", password="", code=200):
        api = self.getapi()
        r = self.testapp.post_json(
            api.login,
            {"user": user, "password": password},
            expect_errors=True,
            headers={'Accept': 'application/json'})
        assert r.status_code == code
        if code == 200:
            password = r.json.get("result", r.json)["password"]
            self.testapp.set_auth(user, password)
            self.auth = user, password

    def login_root(self):
        self.login("root", "")

    def logout(self):
        self.auth = self.testapp.auth = None

    def getuserlist(self):
        r = self.testapp.get_json("/", {"indexes": False})
        assert r.status_code == 200
        return r.json["result"]

    def getindexlist(self, user=None):
        if user is None:
            user = self.testapp.auth[0]
        r = self.testapp.get_json("/%s" % user)
        assert r.status_code == 200
        name = r.json["result"]["username"]
        result = {}
        for index, data in r.json["result"].get("indexes", {}).items():
            result["%s/%s" % (name, index)] = data
        return result

    def getpkglist(self, user=None, indexname=None):
        indexname = self._getindexname(indexname)
        if user is None:
            user = self.testapp.auth[0]
        r = self.testapp.get_json("/%s" % indexname)
        assert r.status_code == 200
        return r.json["result"]["projects"]

    def getreleaseslist(self, name, code=200, user=None, indexname=None):
        indexname = self._getindexname(indexname)
        if user is None:
            user = self.testapp.auth[0]
        r = self.testapp.get_json("/%s/%s" % (indexname, name))
        assert r.status_code == code
        if r.status_code >= 300:
            return
        result = r.json["result"]
        links = set()
        for version in result.values():
            for link in version["+links"]:
                links.add(link["href"])
        return sorted(links)

    def downloadrelease(self, code, url):
        r = self.testapp.get(url, expect_errors=True)
        if isinstance(code, tuple):
            assert r.status_code in code
        else:
            assert r.status_code == code
        if r.status_code < 300:
            return r.body
        return r.json

    def change_password(self, user, password):
        r = self.testapp.patch_json("/%s" % user, dict(password=password))
        assert r.status_code == 200
        self.testapp.auth = (self.testapp.auth[0],
                             r.json["result"]["password"])

    def create_user(self, user, password, email="hello@example.com", code=201):
        reqdict = dict(password=password)
        if email:
            reqdict["email"] = email
        r = self.testapp.put_json("/%s" % user, reqdict, expect_errors=True)
        assert r.status_code == code
        if code == 201:
            res = r.json["result"]
            assert res["username"] == user
            assert res.get("email") == email

    def modify_user(self, user, code=200, password=None, **kwargs):
        reqdict = {}
        if password:
            reqdict["password"] = password
        for key, value in kwargs.items():
            reqdict[key] = value
        r = self.testapp.patch_json("/%s" % user, reqdict, expect_errors=True)
        assert r.status_code == code
        if code == 200:
            assert r.json == dict(message="user updated")

    def create_user_fails(self, user, password, email="hello@example.com"):
        with pytest.raises(webtest.AppError) as excinfo:
            self.create_user(user, password)
        assert "409" in excinfo.value.args[0]

    def create_and_login_user(self, user="someuser", password="123"):
        self.create_user(user, password)
        self.login(user, password)

    def use(self, stagename):
        stagename = stagename.strip("/")
        assert stagename.count("/") == 1, stagename
        self.api = self.getapi(stagename)
        self.api.stagename = stagename
        self.current_stage = stagename
        return self.api

    def getjson(self, path, code=200):
        r = self.testapp.get_json(path, {}, expect_errors=True)
        assert r.status_code == code
        if r.status_code == 302:
            return r.headers["location"]
        return r.json

    def create_index(self, indexname, indexconfig=None, use=True, code=200):
        if indexconfig is None:
            indexconfig = {}
        if "/" in indexname:
            user, index = indexname.split("/")
        else:
            user, password = self.testapp.auth
            index = indexname
        r = self.testapp.put_json("/%s/%s" % (user, index), indexconfig,
                                  expect_errors=True)
        assert r.status_code == code
        if code in (200,201):
            assert r.json["result"]["type"] == indexconfig.get("type", "stage")
            if use:
                return self.use("%s/%s" % (user, index))
        if code in (400,):
            return r.json["message"]

    def modify_index(self, indexname, indexconfig, code=200):
        if "/" in indexname:
            user, index = indexname.split("/")
        else:
            user, password = self.testapp.auth
            index = indexname
        r = self.testapp.patch_json("/%s/%s" % (user, index), indexconfig,
                                  expect_errors=True)
        assert r.status_code == code
        if code in (200,201):
            if isinstance(indexconfig, dict):
                assert r.json["result"]["type"] == indexconfig.get("type", "stage")
            return r.json["result"]
        if code in (400,):
            return r.json["message"]

    def delete_index(self, indexname, code=201, waithooks=False):
        if "/" in indexname:
            user, index = indexname.split("/")
        else:
            user, password = self.testapp.auth
            index = indexname
        r = self.testapp.delete_json("/%s/%s" % (user, index),
                                     expect_errors=True)
        if waithooks:
            self._wait_for_serial_in_result(r)
        assert r.status_code == code

    def set_custom_data(self, data, indexname=None):
        return self.set_key_value("custom_data", data, indexname=indexname)

    def set_key_value(self, key, value, indexname=None):
        indexname = self._getindexname(indexname)
        indexurl = "/" + indexname
        r = self.testapp.get_json(indexurl)
        result = r.json["result"]
        result[key] = value
        r = self.testapp.patch_json(indexurl, result)
        assert r.status_code == 200

    def set_indexconfig_option(self, key, value, indexname=None):
        indexname = self._getindexname(indexname)
        indexurl = "/" + indexname
        r = self.testapp.get_json(indexurl)
        result = r.json["result"]
        result[key] = value
        r = self.testapp.patch_json(indexurl, result)
        assert r.status_code == 200
        assert r.json["result"][key] == value

    def set_mirror_whitelist(self, whitelist, indexname=None):
        indexname = self._getindexname(indexname)
        r = self.testapp.get_json("/%s" % indexname)
        result = r.json["result"]
        result["mirror_whitelist"] = whitelist
        r = self.testapp.patch_json("/%s" % (indexname,), result)
        assert r.status_code == 200

    def set_acl(self, users, acltype="upload", indexname=None):
        indexname = self._getindexname(indexname)
        r = self.testapp.get_json("/%s" % indexname)
        result = r.json["result"]
        if not isinstance(users, list):
            users = users.split(",")
        assert isinstance(users, list)
        result["acl_" + acltype] = users
        r = self.testapp.patch_json("/%s" % (indexname,), result)
        assert r.status_code == 200

    def get_acl(self, acltype="upload", indexname=None):
        indexname = self._getindexname(indexname)
        r = self.testapp.get_json("/%s" % indexname)
        return r.json["result"].get("acl_" + acltype, None)

    def get_mirror_whitelist(self, indexname=None):
        indexname = self._getindexname(indexname)
        r = self.testapp.get_json("/%s" % indexname)
        return r.json["result"]["mirror_whitelist"]

    def delete_project(self, project, code=200, indexname=None,
                       waithooks=False):
        indexname = self._getindexname(indexname)
        r = self.testapp.delete_json("/%s/%s" % (indexname,
                project), {}, expect_errors=True)
        assert r.status_code == code
        if waithooks:
            self._wait_for_serial_in_result(r)

    def set_versiondata(self, metadata, indexname=None, code=200,
                          waithooks=False,
                          set_whitelist=True):
        indexname = self._getindexname(indexname)
        metadata = metadata.copy()
        metadata[":action"] = "submit"
        r = self.testapp.post("/%s/" % indexname, metadata,
                              expect_errors=True)
        assert r.status_code == code
        if r.status_code == 200 and set_whitelist:
            whitelist = set(self.get_mirror_whitelist(indexname=indexname))
            whitelist.add(metadata["name"])
            self.set_mirror_whitelist(sorted(whitelist), indexname=indexname)
        if waithooks:
            self._wait_for_serial_in_result(r)
        return r

    def upload_file_pypi(self, basename, content,
                         name=None, version=None, indexname=None,
                         register=True, code=200, waithooks=False,
                         set_whitelist=True):
        assert isinstance(content, bytes)
        indexname = self._getindexname(indexname)
        #name_version = splitbasename(basename, checkarch=False)
        #if not name:
        #    name = name_version[0]
        #if not version:
        #    version = name_version[1]
        if register and code == 200:
            self.set_versiondata(
                dict(name=name, version=version), set_whitelist=set_whitelist)
        r = self.testapp.post("/%s/" % indexname,
            {":action": "file_upload", "name": name, "version": version,
             "content": Upload(basename, content)}, expect_errors=True)
        assert r.status_code == code
        if waithooks:
            self._wait_for_serial_in_result(r)

        # return the file url so users/callers can easily use it
        # (probably the official server response should include the url)
        r.file_url = make_file_url(basename, content, stagename=indexname)
        r.file_url_no_hash = make_file_url(
            basename, content, stagename=indexname, add_hash=False)
        return r

    def push(self, name, version, index, indexname=None, code=200):
        indexname = self._getindexname(indexname)
        req = dict(name=name, version=version, targetindex=index)
        r = self.testapp.push(
            '/%s' % indexname, json.dumps(req), expect_errors=True)
        assert r.status_code == code
        return r

    def get_release_paths(self, project):
        r = self.get_simple(project)
        pkg_url = URL(r.request.url)
        paths = [pkg_url.joinpath(link["href"]).path
                 for link in BeautifulSoup(r.body, "html.parser").findAll("a")]
        return paths

    def upload_doc(self, basename, content, name, version, indexname=None,
                         code=200, waithooks=False):
        indexname = self._getindexname(indexname)
        form = {":action": "doc_upload", "name": name,
                "content": Upload(basename, content)}
        if version:
            form["version"] = version
        r = self.testapp.post("/%s/" % indexname, form, expect_errors=True)
        assert r.status_code == code
        if waithooks:
            self._wait_for_serial_in_result(r)
        return r

    def upload_toxresult(self, path, content, code=200, waithooks=False):
        r = self.testapp.post(path, content, expect_errors=True)
        assert r.status_code == code
        if waithooks:
            self._wait_for_serial_in_result(r)
        return r

    def get_simple(self, project, code=200):
        r = self.testapp.get(self.api.simpleindex + project + '/',
                             expect_errors=True)
        assert r.status_code == code
        return r


from webtest import TestApp as TApp
from webtest import TestResponse


@pytest.fixture
def noiter(monkeypatch, request):
    l = []

    @property
    def body(self):
        if self.headers["Content-Type"] != "application/octet-stream":
            return self.body_old
        if self.app_iter:
            l.append(self.app_iter)

    monkeypatch.setattr(TestResponse, "body_old", TestResponse.body,
                        raising=False)
    monkeypatch.setattr(TestResponse, "body", body)
    yield
    for x in l:
        x.close()


class MyTestApp(TApp):
    auth = None

    def __init__(self, *args, **kwargs):
        super(MyTestApp, self).__init__(*args, **kwargs)
        self.headers = {}

    def set_auth(self, user, password):
        self.auth = (user, password)

    def set_header_default(self, name, value):
        self.headers[str(name)] = str(value)

    def _gen_request(self, method, url, params=None, headers=None, **kw):
        headers = {} if headers is None else headers.copy()
        if self.auth:
            if not headers:
                headers = kw["headers"] = {}
            headers["X-Devpi-Auth"] = b64encode("%s:%s" % self.auth)
            #print ("setting auth header %r %s %s" % (auth, method, url))

        # fill headers with defaults
        for name, val in self.headers.items():
            headers.setdefault(name, val)

        kw["headers"] = headers
        if params is not None:
            kw["params"] = params
        return super(MyTestApp, self)._gen_request(method, url, **kw)

    def post(self, *args, **kwargs):
        code = kwargs.pop("code", None)
        if code is not None and code >= 300:
            kwargs.setdefault("expect_errors", True)
        r = self._gen_request("POST", *args, **kwargs)
        if code is not None:
            assert r.status_code == code
        return r

    def push(self, url, params=None, **kw):
        kw.setdefault("expect_errors", True)
        return self._gen_request("POST", url, params=params, **kw)

    def get(self, *args, **kwargs):
        kwargs.setdefault("expect_errors", True)
        accept = kwargs.pop("accept", None)
        if accept is not None:
            headers = kwargs.setdefault("headers", {})
            headers[str("Accept")] = str(accept)
        follow = kwargs.pop("follow", True)
        response = self._gen_request("GET", *args, **kwargs)
        if follow and response.status_code == 302:
            assert response.location != args[0]
            return self.get(response.location, *args[1:], **kwargs)
        return response

    def xget(self, code, *args, **kwargs):
        if code == 302:
            kwargs["follow"] = False
        r = self.get(*args, **kwargs)
        assert r.status_code == code
        return r

    def xdel(self, code, *args, **kwargs):
        kwargs.setdefault("expect_errors", True)
        r = self._gen_request("DELETE", *args, **kwargs)
        assert r.status_code == code
        return r

    def get_json(self, *args, **kwargs):
        headers = kwargs.setdefault("headers", {})
        headers["Accept"] = "application/json"
        return self.get(*args, **kwargs)


class FunctionalResponseWrapper(object):
    def __init__(self, response):
        self.res = response

    @property
    def status_code(self):
        return self.res.status_code

    @property
    def body(self):
        return self.res.content

    @property
    def json(self):
        return self.res.json()


class MyFunctionalTestApp(MyTestApp):
    def __init__(self, host_port):
        import json
        self.base_url = "http://%s:%s" % host_port
        self.headers = {}
        self.JSONEncoder = json.JSONEncoder

    def _gen_request(self, method, url, params=None,
                     headers=None, extra_environ=None, status=None,
                     upload_files=None, expect_errors=False,
                     content_type=None):
        headers = {} if headers is None else headers.copy()
        if self.auth:
            headers["X-Devpi-Auth"] = b64encode("%s:%s" % self.auth)

        # fill headers with defaults
        for name, val in self.headers.items():
            headers.setdefault(name, val)

        kw = dict(headers=headers)
        if params and params is not webtest.utils.NoDefault:
            if method.lower() in ('post', 'put', 'patch'):
                kw['data'] = params
            else:
                kw['params'] = params
        meth = getattr(requests, method.lower())
        if '://' not in url:
            url = self.base_url + url
        r = meth(url, **kw)
        return FunctionalResponseWrapper(r)


@pytest.fixture
def testapp(request, maketestapp, xom):
    return maketestapp(xom)


def get_open_port(host):
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        s.bind((host, 0))
        s.listen(1)
        port = s.getsockname()[1]
    return port


def wait_for_port(host, port, timeout=60):
    while timeout > 0:
        with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
            s.settimeout(1)
            if s.connect_ex((host, port)) == 0:
                return
        time.sleep(1)
        timeout -= 1
    raise RuntimeError(
        "The port %s on host %s didn't become accessible" % (port, host))


@pytest.fixture(scope="class")
def server_directory():
    import tempfile
    srvdir = py.path.local(
        tempfile.mkdtemp(prefix='test-', suffix='-server-directory'))
    yield srvdir
    srvdir.remove(ignore_errors=True)


@pytest.fixture(scope="module")
def call_devpi_in_dir():
    # let xproc find the correct executable instead of py.test
    devpigenconfig = str(py.path.local.sysfind("devpi-gen-config"))
    devpiimport = str(py.path.local.sysfind("devpi-import"))
    devpiinit = str(py.path.local.sysfind("devpi-init"))
    devpiserver = str(py.path.local.sysfind("devpi-server"))

    def devpi(server_dir, args):
        from devpi_server.genconfig import genconfig
        from devpi_server.importexport import import_
        from devpi_server.init import init
        from devpi_server.main import main
        from _pytest.monkeypatch import MonkeyPatch
        from _pytest.pytester import RunResult
        m = MonkeyPatch()
        m.setenv("DEVPISERVER_SERVERDIR", getattr(server_dir, 'strpath', server_dir))
        cap = py.io.StdCaptureFD()
        cap.startall()
        now = time.time()
        if args[0] == 'devpi-gen-config':
            m.setattr("sys.argv", [devpigenconfig])
            entry_point = genconfig
        elif args[0] == 'devpi-import':
            m.setattr("sys.argv", [devpiimport])
            entry_point = import_
        elif args[0] == 'devpi-init':
            m.setattr("sys.argv", [devpiinit])
            entry_point = init
        elif args[0] == 'devpi-server':
            m.setattr("sys.argv", [devpiserver])
            entry_point = main
        try:
            entry_point(argv=args)
        finally:
            m.undo()
            out, err = cap.reset()
            del cap
        return RunResult(
            0, out.split("\n"), err.split("\n"), time.time() - now)

    return devpi


@pytest.fixture(scope="class")
def master_serverdir(server_directory):
    return server_directory.join("master")


@pytest.fixture(scope="class")
def secretfile(server_directory):
    import base64
    import secrets
    secretfile = server_directory.join('testserver.secret')
    if not secretfile.exists():
        secretfile.write(base64.b64encode(secrets.token_bytes(32)))
        if sys.platform != "win32":
            secretfile.chmod(0o600)
    return secretfile


@pytest.fixture(scope="class")
def master_host_port(request, call_devpi_in_dir, master_serverdir, server_directory, secretfile, storage_info):
    host = 'localhost'
    port = get_open_port(host)
    args = [
        "devpi-server",
        "--role", "master",
        "--secretfile", secretfile.strpath,
        "--argon2-memory-cost", str(LOWER_ARGON2_MEMORY_COST),
        "--argon2-parallelism", str(LOWER_ARGON2_PARALLELISM),
        "--argon2-time-cost", str(LOWER_ARGON2_TIME_COST),
        "--host", host,
        "--port", str(port),
        "--requests-only"]
    storage_args = [
        "--serverdir", master_serverdir.strpath]
    if storage_info["name"] != "sqlite":
        storage_option = "--storage=%s" % storage_info["name"]
        _get_test_storage_options = getattr(
            storage_info["storage"], "_get_test_storage_options", None)
        if _get_test_storage_options:
            storage_options = _get_test_storage_options(master_serverdir)
            storage_option = storage_option + storage_options
        storage_args.append(storage_option)
    if not master_serverdir.join('.nodeinfo').exists():
        subprocess.check_call(
            ["devpi-init"] + storage_args)
    p = subprocess.Popen(args + storage_args)
    try:
        wait_for_port(host, port)
        yield (host, port)
    finally:
        p.terminate()
        p.wait()


@pytest.fixture(scope="class")
def replica_serverdir(server_directory):
    return server_directory.join("replica")


@pytest.fixture(scope="class")
def replica_host_port(request, call_devpi_in_dir, master_host_port, replica_serverdir, secretfile, storage_info):
    host = 'localhost'
    port = get_open_port(host)
    args = [
        "devpi-server",
        "--secretfile", secretfile.strpath,
        "--argon2-memory-cost", str(LOWER_ARGON2_MEMORY_COST),
        "--argon2-parallelism", str(LOWER_ARGON2_PARALLELISM),
        "--argon2-time-cost", str(LOWER_ARGON2_TIME_COST),
        "--host", host, "--port", str(port)]
    storage_args = [
        "--serverdir", replica_serverdir.strpath]
    if storage_info["name"] != "sqlite":
        storage_option = "--storage=%s" % storage_info["name"]
        _get_test_storage_options = getattr(
            storage_info["storage"], "_get_test_storage_options", None)
        if _get_test_storage_options:
            storage_options = _get_test_storage_options(replica_serverdir)
            storage_option = storage_option + storage_options
        storage_args.append(storage_option)
    if not replica_serverdir.join('.nodeinfo').exists():
        subprocess.check_call([
            "devpi-init",
            "--role", "replica",
            "--master-url", "http://%s:%s" % master_host_port] + storage_args)
    p = subprocess.Popen(args + storage_args)
    try:
        wait_for_port(host, port)
        yield (host, port)
    finally:
        p.terminate()
        p.wait()


nginx_conf_content = """
worker_processes  1;
daemon off;
pid nginx.pid;
error_log nginx_error.log;

events {
    worker_connections  32;
}

http {
    access_log off;
    default_type  application/octet-stream;
    sendfile        on;
    keepalive_timeout 0;
    include nginx-devpi.conf;
}
"""


def _nginx_host_port(host, port, call_devpi_in_dir, server_directory):
    # let xproc find the correct executable instead of py.test
    nginx = py.path.local.sysfind("nginx")
    if nginx is None:
        pytest.skip("No nginx executable found.")
    nginx = str(nginx)

    orig_dir = server_directory.chdir()
    try:
        args = ["devpi-gen-config", "--host", host, "--port", str(port)]
        if not server_directory.join('.nodeinfo').exists():
            call_devpi_in_dir(server_directory.strpath, ["devpi-init"])
        call_devpi_in_dir(
            server_directory.strpath,
            args)
    finally:
        orig_dir.chdir()
    nginx_directory = server_directory.join("gen-config")
    nginx_devpi_conf = nginx_directory.join("nginx-devpi.conf")
    nginx_port = get_open_port(host)
    nginx_devpi_conf_content = nginx_devpi_conf.read()
    nginx_devpi_conf_content = nginx_devpi_conf_content.replace(
        "listen 80;",
        "listen %s;" % nginx_port)
    nginx_devpi_conf.write(nginx_devpi_conf_content)
    nginx_conf = nginx_directory.join("nginx.conf")
    nginx_conf.write(nginx_conf_content)
    try:
        subprocess.check_output([
            nginx, "-t",
            "-c", nginx_conf.strpath,
            "-p", nginx_directory.strpath], stderr=subprocess.STDOUT)
    except subprocess.CalledProcessError as e:
        print(e.output, file=sys.stderr)
        raise
    p = subprocess.Popen([
        nginx, "-c", nginx_conf.strpath, "-p", nginx_directory.strpath])
    return (p, nginx_port)


@pytest.fixture(scope="class")
def nginx_host_port(request, call_devpi_in_dir, server_directory):
    if sys.platform.startswith("win"):
        pytest.skip("no nginx on windows")
    # we need the skip above before master_host_port is called
    (host, port) = request.getfixturevalue("master_host_port")
    (p, nginx_port) = _nginx_host_port(
        host, port, call_devpi_in_dir, server_directory)
    try:
        wait_for_port(host, nginx_port)
        yield (host, nginx_port)
    finally:
        p.terminate()
        p.wait()


@pytest.fixture(scope="class")
def nginx_replica_host_port(request, call_devpi_in_dir, server_directory):
    if sys.platform.startswith("win"):
        pytest.skip("no nginx on windows")
    # we need the skip above before master_host_port is called
    (host, port) = request.getfixturevalue("replica_host_port")
    (p, nginx_port) = _nginx_host_port(
        host, port, call_devpi_in_dir, server_directory)
    try:
        wait_for_port(host, nginx_port)
        yield (host, nginx_port)
    finally:
        p.terminate()
        p.wait()


@pytest.fixture(scope="session")
def simpypiserver():
    from .simpypi import httpserver, SimPyPIRequestHandler
    import threading
    host = 'localhost'
    port = get_open_port(host)
    server = httpserver.HTTPServer((host, port), SimPyPIRequestHandler)
    thread = threading.Thread(target=server.serve_forever)
    thread.daemon = True
    thread.start()
    wait_for_port(host, port, 5)
    print("Started simpypi server %s:%s" % server.server_address)
    return server


@pytest.fixture
def simpypi(simpypiserver):
    from .simpypi import SimPyPI
    simpypiserver.simpypi = SimPyPI(simpypiserver.server_address)
    return simpypiserver.simpypi


# incremental testing

def pytest_runtest_makereport(item, call):
    if "incremental" in item.keywords:
        if call.excinfo is not None:
            parent = item.parent
            parent._previousfailed = item


def pytest_runtest_setup(item):
    if "incremental" in item.keywords:
        previousfailed = getattr(item.parent, "_previousfailed", None)
        if previousfailed is not None:
            pytest.xfail("previous test failed (%s)" %previousfailed.name)


@pytest.fixture
def gen():
    return Gen()


class Gen:
    def __init__(self):
        self._md5 = hashlib.md5()

    def pypi_package_link(self, pkgname, md5=True):
        link = "https://pypi.org/package/some/%s" % pkgname
        if md5 == True:
            self._md5.update(link.encode("utf8"))  # basically random
            link += "#md5=%s" % self._md5.hexdigest()
        elif md5:
            link += "#md5=%s" % md5
        return URL(link)


@pytest.fixture
def pyramidconfig():
    from pyramid.testing import setUp, tearDown
    config = setUp()
    yield config
    tearDown()


@pytest.fixture
def dummyrequest(pyramidconfig):
    from pyramid.testing import DummyRequest
    request = DummyRequest()
    pyramidconfig.begin(request=request)
    yield request


@pytest.fixture
def blank_request():
    from pyramid.request import Request

    def blank_request(*args, **kwargs):
        return Request.blank("/blankpath", *args, **kwargs)

    return blank_request


@pytest.fixture(params=[None, "tox38"])
def tox_result_data(request):
    from test_devpi_server.example import tox_result_data
    import copy
    tox_result_data = copy.deepcopy(tox_result_data)
    if request.param == "tox38":
        retcode = int(tox_result_data['testenvs']['py27']['test'][0]['retcode'])
        tox_result_data['testenvs']['py27']['test'][0]['retcode'] = retcode
    return tox_result_data
