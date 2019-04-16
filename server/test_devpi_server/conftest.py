from __future__ import print_function
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
from bs4 import BeautifulSoup
from contextlib import closing
from devpi_server import extpypi
from devpi_server.config import get_pluginmanager
from devpi_server.main import XOM, parseoptions
from devpi_common.url import URL
from devpi_server.extpypi import PyPIStage
from devpi_server.log import threadlog, thread_clear_log
from pyramid.authentication import b64encode
from pyramid.compat import escape
from pyramid.httpexceptions import status_map

import hashlib
try:
    from queue import Queue as BaseQueue
except ImportError:
    from Queue import Queue as BaseQueue

try:
    import http.server as httpserver
except ImportError:
    import BaseHTTPServer as httpserver


def make_file_url(basename, content, stagename=None, baseurl="http://localhost/"):
    from devpi_server.filestore import get_default_hash_spec, make_splitdir
    hash_spec = get_default_hash_spec(content)
    hashdir = "/".join(make_splitdir(hash_spec))
    s = "%s{stage}/+f/%s/%s#%s" %(baseurl, hashdir, basename, hash_spec)
    if stagename is not None:
        s = s.format(stage=stagename)
    return s

class TimeoutQueue(BaseQueue):
    def get(self, timeout=2):
        return BaseQueue.get(self, timeout=timeout)

log = threadlog

@pytest.fixture(autouse=True)
def _clear():
    thread_clear_log()


@pytest.yield_fixture
def pool():
    from devpi_server.mythread  import ThreadPool
    pool = ThreadPool()
    yield pool
    pool.shutdown()

@pytest.fixture
def queue():
    return TimeoutQueue()

@pytest.fixture
def Queue():
    return TimeoutQueue

@pytest.fixture()
def caplog(caplog):
    import logging
    """ enrich the pytest-catchlog funcarg. """
    def getrecords(msgrex=None, minlevel="DEBUG"):
        if msgrex is not None:
            msgrex = re.compile(msgrex)
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
def gentmp(request):
    tmpdirhandler = request.config._tmpdirhandler
    cache = []
    def gentmp(name=None):
        if not cache:
            prefix = re.sub(r"[\W]", "_", request.node.name)
            basedir = tmpdirhandler.mktemp(prefix, numbered=True)
            cache.append(basedir)
        else:
            basedir = cache[0]
        if name:
            return basedir.mkdir(name)
        return py.path.local.make_numbered_dir(prefix="gentmp",
                keep=0, rootdir=basedir, lock_timeout=None)
    return gentmp


@pytest.yield_fixture(autouse=True)
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


@pytest.yield_fixture(autouse=True, scope="session")
def speed_up_sqlite():
    from devpi_server.keyfs_sqlite import Storage
    old = Storage.ensure_tables_exist
    def make_unsynchronous(self, old=old):
        conn = old(self)
        with self.get_connection() as conn:
            conn._sqlconn.execute("PRAGMA synchronous=OFF")
        return
    Storage.ensure_tables_exist = make_unsynchronous
    yield
    Storage.ensure_tables_exist = old


@pytest.yield_fixture(autouse=True, scope="session")
def speed_up_sqlite_fs():
    from devpi_server.keyfs_sqlite_fs import Storage
    old = Storage.ensure_tables_exist
    def make_unsynchronous(self, old=old):
        conn = old(self)
        with self.get_connection() as conn:
            conn._sqlconn.execute("PRAGMA synchronous=OFF")
        return
    Storage.ensure_tables_exist = make_unsynchronous
    yield
    Storage.ensure_tables_exist = old


@pytest.fixture(scope="session")
def mock():
    try:
        from unittest import mock
    except ImportError:
        import mock
    return mock


@pytest.fixture(scope="session")
def storage_info(request):
    from pydoc import locate
    backend = getattr(request.config.option, 'backend', None)
    if backend is None:
        backend = 'devpi_server.keyfs_sqlite_fs'
    plugin = locate(backend)
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
        plugins = [
            plugin[0] if isinstance(plugin, tuple) else plugin
            for plugin in plugins]
        for plugin in [auth_basic, auth_devpi, storage_info["_test_plugin"]]:
            if plugin not in plugins:
                plugins.append(plugin)
        pm = get_pluginmanager(load_entrypoints=False)
        for plugin in plugins:
            pm.register(plugin)
        serverdir = gentmp()
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
            if not request.node.get_closest_marker("nomockprojectsremote"):
                monkeypatch.setattr(extpypi.PyPIStage, "_get_remote_projects",
                    lambda self: set())
            add_pypistage_mocks(monkeypatch, httpget)
        # initialize default indexes
        from devpi_server.main import set_default_indexes
        if not xom.config.args.master_url:
            with xom.keyfs.transaction(write=True):
                set_default_indexes(xom.model)
        if request.node.get_closest_marker("with_replica_thread"):
            from devpi_server.replica import ReplicaThread
            rt = ReplicaThread(xom)
            xom.replica_thread = rt
            xom.thread_pool.register(rt)
            xom.thread_pool.start_one(rt)
        if request.node.get_closest_marker("start_threads"):
            xom.thread_pool.start()
        elif request.node.get_closest_marker("with_notifier"):
            xom.thread_pool.start_one(xom.keyfs.notifier)
        request.addfinalizer(xom.thread_pool.shutdown)
        return xom
    return makexom


@pytest.fixture
def replica_xom(request, makexom):
    from devpi_server.replica import register_key_subscribers
    master_url = "http://localhost:3111"
    xom = makexom(["--master", master_url])
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


def make_simple_pkg_info(name, text="", pkgver=None, hash_type=None,
                         pypiserial=None, requires_python=None):
    class ret:
        hash_spec = ""
    if requires_python:
        requires_python = ' data-requires-python="%s"' % escape(requires_python)
    else:
        requires_python = ''
    if pkgver is not None:
        assert not text
        if hash_type and "#" not in pkgver:
            hv = (pkgver + str(pypiserial)).encode("ascii")
            hash_value = getattr(hashlib, hash_type)(hv).hexdigest()
            ret.hash_spec = "%s=%s" %(hash_type, hash_value)
            pkgver += "#" + ret.hash_spec
        text = '<a href="../../{name}/{pkgver}"{requires_python}>{pkgver}</a>'.format(
            name=name, pkgver=pkgver, requires_python=requires_python)
    elif text and "{md5}" in text:
        text = text.format(md5=getmd5(text))
    elif text and "{sha256}" in text:
        text = text.format(sha256=getsha256(text))
    return ret, text


@pytest.fixture
def httpget(pypiurls):
    class MockHTTPGet:
        def __init__(self):
            self.url2response = {}
            self._md5 = hashlib.md5()

        def __call__(self, url, allow_redirects=False, extra_headers=None, **kw):
            class mockresponse:
                def __init__(xself, url):
                    fakeresponse = self.url2response.get(url)
                    if fakeresponse is None:
                        fakeresponse = dict(status_code = 404)
                    xself.__dict__.update(fakeresponse)
                    if "url" not in fakeresponse:
                        xself.url = url
                    xself.allow_redirects = allow_redirects
                    if "content" in fakeresponse:
                        xself.raw = py.io.BytesIO(fakeresponse["content"])

                def __repr__(xself):
                    return "<mockresponse %s url=%s>" % (xself.status_code,
                                                         xself.url)
            r = mockresponse(url)
            log.debug("returning %s", r)
            return r

        def mockresponse(self, mockurl, **kw):
            kw.setdefault("status_code", 200)
            kw.setdefault("reason", getattr(
                status_map.get(kw["status_code"]),
                "title",
                "Devpi Mock Error"))
            log.debug("set mocking response %s %s", mockurl, kw)
            self.url2response[mockurl] = kw

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
            self.mockresponse(remoteurl + name + "/", text=text, **kw)
            return ret

        def _getmd5digest(self, s):
            self._md5.update(s.encode("utf8"))
            return self._md5.hexdigest()

    return MockHTTPGet()

@pytest.fixture
def filestore(xom):
    return xom.filestore

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
    # add some mocking helpers
    PyPIStage.url2response = httpget.url2response
    def mock_simple(self, name, text=None, pypiserial=10000, **kw):
        self.cache_retrieve_times.expire(name)
        return self.httpget.mock_simple(name,
                 text=text, pypiserial=pypiserial, **kw)
    monkeypatch.setattr(PyPIStage, "mock_simple", mock_simple, raising=False)

    def mock_simple_projects(self, projectlist):
        t = "".join('<a href="%s">%s</a>\n' % (name, name) for name in projectlist)
        threadlog.debug("patching simple page with: %s" %(t))
        self.httpget.mockresponse(self.mirror_url, code=200, text=t)

    monkeypatch.setattr(PyPIStage, "mock_simple_projects",
                        mock_simple_projects, raising=False)

    def mock_extfile(self, path, content, **kw):
        headers = {"content-length": len(content),
                   "content-type": mimetypes.guess_type(path),
                   "last-modified": "today",}
        url = URL(self.mirror_url).joinpath(path)
        return self.httpget.mockresponse(url.url, content=content,
                                         headers=headers, **kw)
    monkeypatch.setattr(PyPIStage, "mock_extfile", mock_extfile, raising=False)

@pytest.fixture
def pypiurls():
    from devpi_server.main import _pypi_ixconfig_default
    class PyPIURL:
        def __init__(self):
            self.simple = _pypi_ixconfig_default['mirror_url']
    return PyPIURL()


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
        r = self.testapp.post_json(api.login,
                                  {"user": user, "password": password},
                                  expect_errors=True)
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
        r = self.testapp.get("/", {"indexes": False}, {"Accept": "application/json"})
        assert r.status_code == 200
        return r.json["result"]

    def getindexlist(self, user=None):
        if user is None:
            user = self.testapp.auth[0]
        r = self.testapp.get("/%s" % user, accept="application/json")
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
        r = self.testapp.get("/%s" % indexname, accept="application/json")
        assert r.status_code == 200
        return r.json["result"]["projects"]

    def getreleaseslist(self, name, code=200, user=None, indexname=None):
        indexname = self._getindexname(indexname)
        if user is None:
            user = self.testapp.auth[0]
        r = self.testapp.get("/%s/%s" % (indexname, name), accept="application/json")
        assert r.status_code == 200
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
        assert py.builtin._isbytes(content)
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


@pytest.yield_fixture
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
        self.x = 1
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


class SimPyPIRequestHandler(httpserver.BaseHTTPRequestHandler):
    def do_GET(self):
        def start_response(status, headers):
            self.send_response(status)
            for key, value in headers.items():
                self.send_header(key, value)
            self.end_headers()

        simpypi = self.server.simpypi
        headers = {
            'X-Simpypi-Method': 'GET'}
        p = self.path.split('/')
        if len(p) == 4 and p[0] == '' and p[1] == 'simple' and p[3] == '':
            # project listing
            project = simpypi.projects.get(p[2])
            if project is not None:
                releases = project['releases']
                simpypi.add_log(
                    "do_GET", self.path, "found",
                    project['title'], "with", list(releases))
                start_response(200, headers)
                self.wfile.write(b'\n'.join(releases))
                return
        elif p == ['', 'simple', ''] or p == ['', 'simple']:
            # root listing
            projects = [
                '<a href="/simple/%s/">%s</a>' % (k, v['title'])
                for k, v in simpypi.projects.items()]
            simpypi.add_log("do_GET", self.path, "found", list(simpypi.projects))
            start_response(200, headers)
            self.wfile.write(b'\n'.join(x.encode('utf-8') for x in projects))
            return
        elif self.path in simpypi.files:
            # file serving
            f = simpypi.files[self.path]
            content = f['content']
            if 'length' in f:
                headers['Content-Length'] = f['length']
                content = content[:f['length']]
            start_response(200, headers)
            simpypi.add_log("do_GET", self.path, "sending")
            if not f['stream']:
                self.wfile.write(content)
                simpypi.add_log("do_GET", self.path, "sent")
                return
            else:
                chunksize = f['chunksize']
                callback = f.get('callback')
                for i in range(len(content) // chunksize):
                    data = content[i * chunksize:(i + 1) * chunksize]
                    if not data:
                        break
                    self.wfile.write(data)
                    if callback:
                        callback(i * chunksize)
                    simpypi.add_log(
                        "do_GET", self.path,
                        "streamed %i bytes" % (i * chunksize))
                return
        simpypi.add_log("do_GET", self.path, "not found")
        start_response(404, headers)


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


@pytest.yield_fixture(scope="module")
def server_directory():
    import tempfile
    srvdir = py.path.local(
        tempfile.mkdtemp(prefix='test-', suffix='-server-directory'))
    yield srvdir
    srvdir.remove(ignore_errors=True)


@pytest.fixture(scope="module")
def call_devpi_in_dir():
    # let xproc find the correct executable instead of py.test
    devpiserver = str(py.path.local.sysfind("devpi-server"))

    def devpi(server_dir, args):
        from devpi_server.main import main
        from _pytest.monkeypatch import MonkeyPatch
        from _pytest.pytester import RunResult
        m = MonkeyPatch()
        m.setenv("DEVPISERVER_SERVERDIR", getattr(server_dir, 'strpath', server_dir))
        m.setattr("sys.argv", [devpiserver])
        cap = py.io.StdCaptureFD()
        cap.startall()
        now = time.time()
        try:
            main(args)
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


@pytest.yield_fixture(scope="class")
def master_host_port(request, call_devpi_in_dir, master_serverdir):
    host = 'localhost'
    port = get_open_port(host)
    args = [
        "devpi-server",
        "--serverdir", master_serverdir.strpath,
        "--role", "master",
        "--host", host,
        "--port", str(port),
        "--requests-only"]
    if not master_serverdir.join('.nodeinfo').exists():
        subprocess.check_call(
            args + ["--init"])
    p = subprocess.Popen(args)
    try:
        wait_for_port(host, port)
        yield (host, port)
    finally:
        p.terminate()
        p.wait()


@pytest.fixture(scope="class")
def replica_serverdir(server_directory):
    return server_directory.join("replica")


@pytest.yield_fixture(scope="class")
def replica_host_port(request, call_devpi_in_dir, master_host_port, replica_serverdir):
    host = 'localhost'
    port = get_open_port(host)
    args = [
        "devpi-server", "--start",
        "--host", host, "--port", str(port),
        "--master-url", "http://%s:%s" % master_host_port]
    if not replica_serverdir.join('.nodeinfo').exists():
        args.append("--init")
    call_devpi_in_dir(
        replica_serverdir.strpath,
        args)
    try:
        wait_for_port(host, port)
        yield (host, port)
    finally:
        call_devpi_in_dir(
            replica_serverdir.strpath,
            ["devpi-server", "--stop"])


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
        args = ["devpi-server", "--gen-config", "--host", host, "--port", str(port)]
        if not server_directory.join('.nodeinfo').exists():
            args.append("--init")
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
    wait_for_port(host, nginx_port)
    return (p, nginx_port)


@pytest.yield_fixture(scope="class")
def nginx_host_port(request, call_devpi_in_dir, server_directory):
    if sys.platform.startswith("win"):
        pytest.skip("no nginx on windows")
    # we need the skip above before master_host_port is called
    (host, port) = request.getfixturevalue("master_host_port")
    (p, nginx_port) = _nginx_host_port(
        host, port, call_devpi_in_dir, server_directory)
    try:
        yield (host, nginx_port)
    finally:
        p.terminate()
        p.wait()


@pytest.yield_fixture(scope="class")
def nginx_replica_host_port(replica_host_port, call_devpi_in_dir, server_directory):
    (host, port) = replica_host_port
    (p, nginx_port) = _nginx_host_port(
        host, port, call_devpi_in_dir, server_directory)
    try:
        yield (host, nginx_port)
    finally:
        p.terminate()
        p.wait()


@pytest.fixture(scope="session")
def simpypiserver():
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


class SimPyPI:
    def __init__(self, address):
        self.baseurl = "http://%s:%s" % address
        self.simpleurl = "%s/simple" % self.baseurl
        self.projects = {}
        self.files = {}
        self.clear_log()

    def clear_log(self):
        self.log = []

    def add_log(self, *args):
        msg = ' '.join(str(x) for x in args)
        print(msg, file=sys.stderr)
        self.log.append(msg)

    def add_project(self, name, title=None):
        if title is None:
            title = name
        self.projects.setdefault(
            name, dict(
                title=title,
                releases=set(),
                pypiserial=None))
        return self.projects[name]

    def remove_project(self, name):
        self.projects.pop(name)

    def add_release(self, name, title=None, text="", pkgver=None, hash_type=None,
                    pypiserial=None, requires_python=None, **kw):
        project = self.add_project(name, title=title)
        ret, text = make_simple_pkg_info(
            name, text=text, pkgver=pkgver, hash_type=hash_type,
            pypiserial=pypiserial, requires_python=requires_python)
        assert text
        project['releases'].add(text.encode('utf-8'))

    def add_file(self, relpath, content, stream=False, chunksize=1024,
                 length=None, callback=None):
        if length is None:
            length = len(content)
        info = dict(
            content=content,
            stream=stream,
            chunksize=chunksize,
            callback=callback)
        if length is not False:
            info['length'] = length
        self.files[relpath] = info

    def remove_file(self, relpath):
        del self.files[relpath]


@pytest.fixture
def simpypi(simpypiserver):
    simpypiserver.simpypi = SimPyPI(simpypiserver.server_address)
    return simpypiserver.simpypi


### incremental testing

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

#
#  various requests related mocking functionality
#  (XXX consolidate, release a plugin?)
#
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.response import HTTPResponse
import fnmatch


@pytest.fixture
def reqmock(monkeypatch):
    mr = mocked_request()
    def get_adapter(self, url):
        return MockAdapter(mr, url)
    monkeypatch.setattr("requests.sessions.Session.get_adapter", get_adapter)
    return mr

class MockAdapter:
    def __init__(self, mock_request, url):
        self.url = url
        self.mock_request = mock_request

    def send(self, request, **kwargs):
        return self.mock_request.process_request(request, kwargs)


class mocked_request:
    def __init__(self):
        self.url2reply = {}

    def process_request(self, request, kwargs):
        url = request.url
        response = self.url2reply.get((url, request.method))
        if response is None:
            response = self.url2reply.get((url, None))
            if response is None:
                for (name, method), response in self.url2reply.items():
                    if method is None or method == request.method:
                        if fnmatch.fnmatch(request.url, name):
                            break
                else:
                    raise Exception("not mocked call to %s" % url)
        response.add_request(request)
        r = HTTPAdapter().build_response(request, response)
        return r

    def mockresponse(self, url, code, method=None, data=None, headers=None,
                     on_request=None, reason=None):
        if not url:
            url = "*"
        r = ReqReply(code=code, data=data, headers=headers,
                     on_request=on_request, reason=reason)
        if method is not None:
            method = method.upper()
        self.url2reply[(url, method)] = r
        return r
    mock = mockresponse

class ReqReply(HTTPResponse):
    def __init__(self, code, data, headers, on_request, reason=None):
        if py.builtin._istext(data):
            data = data.encode("utf-8")
        super(ReqReply, self).__init__(body=py.io.BytesIO(data),
                                       status=code,
                                       headers=headers,
                                       reason=reason,
                                       preload_content=False)
        self.requests = []
        self.on_request = on_request

    def add_request(self, request):
        if self.on_request:
            self.on_request(request)
        self.requests.append(request)

#
#  end requests related mocking functionality
#

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

def getmd5(s):
    return hashlib.md5(s.encode("utf8")).hexdigest()

def getsha256(s):
    return hashlib.sha256(s.encode("utf8")).hexdigest()


@pytest.yield_fixture
def pyramidconfig():
    from pyramid.testing import setUp, tearDown
    config = setUp()
    yield config
    tearDown()


@pytest.yield_fixture
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
