import re
import logging
from webtest.forms import Upload
import webtest
import mimetypes

import pytest
import py
from bs4 import BeautifulSoup
from devpi_server.config import get_pluginmanager
from devpi_server.main import XOM, parseoptions
from devpi_common.url import URL
from devpi_server.extpypi import XMLProxy
from devpi_server.extpypi import PyPIStage
from devpi_server.log import threadlog, thread_clear_log
from pyramid.authentication import b64encode

import hashlib
try:
    from queue import Queue as BaseQueue
except ImportError:
    from Queue import Queue as BaseQueue

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

def pytest_addoption(parser):
    parser.addoption("--slow", action="store_true", default=False,
        help="run slow tests involving remote services (pypi.python.org)")

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
    """ enrich the pytest-capturelog funcarg. """
    caplog.setLevel(logging.DEBUG)
    def getrecords(msgrex=None, minlevel="DEBUG"):
        if msgrex is not None:
            msgrex = re.compile(msgrex)
        minlevelno = {"DEBUG": 10, "INFO": 20, "WARNING": 30,
                      "ERROR": 40, "FATAL": 50}.get(minlevel)
        recs = []
        for rec in caplog.records():
            if rec.levelno < minlevelno:
                continue
            if msgrex is not None and not msgrex.search(rec.getMessage()):
                continue
            recs.append(rec)
        return recs
    caplog.getrecords = getrecords
    return caplog

@pytest.fixture
def gentmp(request):
    tmpdirhandler = request.config._tmpdirhandler
    cache = []
    def gentmp(name=None):
        if not cache:
            prefix = re.sub("[\W]", "_", request.node.name)
            basedir = tmpdirhandler.mktemp(prefix, numbered=True)
            cache.append(basedir)
        else:
            basedir = cache[0]
        if name:
            return basedir.mkdir(name)
        return py.path.local.make_numbered_dir(prefix="gentmp",
                keep=0, rootdir=basedir, lock_timeout=None)
    return gentmp

@pytest.fixture
def xom_notmocked(request, makexom):
    return makexom(mocking=False)

@pytest.yield_fixture(autouse=True)
def auto_transact(request):
    names = request.fixturenames
    if ("xom" not in names and "keyfs" not in names) or (
        request.node.get_marker("notransaction")):
        yield
        return
    keyfs = request.getfuncargvalue("keyfs")

    write = True if request.node.get_marker("writetransaction") else False
    keyfs.begin_transaction_in_thread(write=write)
    yield
    try:
        keyfs.rollback_transaction_in_thread()
    except AttributeError:  # already finished within the test
        pass


@pytest.fixture
def xom(request, makexom):
    xom = makexom([])
    return xom

@pytest.yield_fixture(autouse=True, scope="session")
def speed_up_sql():
    from devpi_server.keyfs import Filesystem
    old = Filesystem.get_sqlconn
    def make_unsynchronous(self, old=old):
        conn = old(self)
        conn.execute("PRAGMA synchronous=OFF")
        return conn
    Filesystem.get_sqlconn = make_unsynchronous
    yield
    Filesystem.get_sqlconn = old

@pytest.fixture(scope="session")
def mock():
    try:
        from unittest import mock
    except ImportError:
        import mock
    return mock

@pytest.fixture
def makexom(request, gentmp, httpget, monkeypatch, mock):
    def makexom(opts=(), httpget=httpget, proxy=None, mocking=True, plugins=()):
        from devpi_server import auth_basic
        from devpi_server import auth_devpi
        plugins = list(plugins) + [(auth_basic, None), (auth_devpi, None)]
        pm = get_pluginmanager()
        for plugin in plugins:
            pm.register(plugin)
        serverdir = gentmp()
        fullopts = ["devpi-server", "--serverdir", serverdir] + list(opts)
        fullopts = [str(x) for x in fullopts]
        config = parseoptions(pm, fullopts)
        config.init_nodeinfo()
        if mocking:
            if proxy is None:
                proxy = mock.create_autospec(XMLProxy)
                proxy.list_packages_with_serial.return_value = {}
            xom = XOM(config, proxy=proxy, httpget=httpget)
            add_pypistage_mocks(monkeypatch, httpget)
        else:
            xom = XOM(config)
        # initialize default indexes
        from devpi_server.main import set_default_indexes
        if not xom.config.args.master_url:
            with xom.keyfs.transaction(write=True):
                set_default_indexes(xom.model)
        if mocking:
            xom.pypimirror.init_pypi_mirror(proxy)
        if request.node.get_marker("start_threads"):
            xom.thread_pool.start()
        elif request.node.get_marker("with_notifier"):
            xom.thread_pool.start_one(xom.keyfs.notifier)
        request.addfinalizer(xom.thread_pool.shutdown)
        return xom
    return makexom


@pytest.fixture
def replica_xom(request, makexom):
    from devpi_server.replica import PyPIProxy
    master_url = "http://localhost:3111"
    xom = makexom(["--master", master_url])
    xom.proxy = PyPIProxy(xom._httpsession, xom.config.master_url)
    return xom


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
    class MockHTTPGet:
        def __init__(self):
            self.url2response = {}
            self._md5 = py.std.hashlib.md5()

        def __call__(self, url, allow_redirects=False, extra_headers=None):
            class mockresponse:
                def __init__(xself, url):
                    fakeresponse = self.url2response.get(url)
                    if fakeresponse is None:
                        fakeresponse = dict(status_code = 404)
                    xself.__dict__.update(fakeresponse)
                    if "url" not in fakeresponse:
                        xself.url = url
                    xself.allow_redirects = allow_redirects
                def __repr__(xself):
                    return "<mockresponse %s url=%s>" % (xself.status_code,
                                                         xself.url)
            r = mockresponse(url)
            log.debug("returning %s", r)
            return r

        def mockresponse(self, mockurl, **kw):
            if "status_code" not in kw:
                kw["status_code"] = 200
            log.debug("set mocking response %s %s", mockurl, kw)
            self.url2response[mockurl] = kw

        def mock_simple(self, name, text=None, pkgver=None, hash_type=None,
            pypiserial=10000, **kw):
            class ret:
                hash_spec = ""
            if pkgver is not None:
                assert not text
                if hash_type and "#" not in pkgver:
                    hv = (pkgver + str(pypiserial)).encode("ascii")
                    hash_value = getattr(hashlib, hash_type)(hv).hexdigest()
                    ret.hash_spec = "%s=%s" %(hash_type, hash_value)
                    pkgver += "#" + ret.hash_spec
                text = '<a href="../../pkg/{pkgver}" />'.format(pkgver=pkgver)
            elif text and "{md5}" in text:
                text = text.format(md5=getmd5(text))
            elif text and "{sha256}" in text:
                text = text.format(sha256=getsha256(text))
            headers = kw.setdefault("headers", {})
            headers["X-PYPI-LAST-SERIAL"] = pypiserial
            self.mockresponse(pypiurls.simple + name + "/",
                                      text=text, **kw)
            return ret

        def _getmd5digest(self, s):
            self._md5.update(s.encode("utf8"))
            return self._md5.hexdigest()

        def setextfile(self, path, content, **kw):
            headers = {"content-length": len(content),
                       "content-type": mimetypes.guess_type(path),
                       "last-modified": "today",}
            if path.startswith("/") and pypiurls.base.endswith("/"):
                path = path.lstrip("/")
            return self.mockresponse(pypiurls.base + path,
                                     raw=py.io.BytesIO(content),
                                     headers=headers,
                                     **kw)


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
def pypistage(xom):
    return PyPIStage(xom)

def add_pypistage_mocks(monkeypatch, httpget):
    # add some mocking helpers
    PyPIStage.url2response = httpget.url2response
    def mock_simple(self, name, text=None, pypiserial=10000, **kw):
        call = lambda: \
                 self.pypimirror.process_changelog([(name, 0,0,0, pypiserial)])
        if not hasattr(self.keyfs, "tx"):
            with self.keyfs.transaction(write=True):
                call()
        else:
            call()
        return self.httpget.mock_simple(name,
                text=text, pypiserial=pypiserial, **kw)
    monkeypatch.setattr(PyPIStage, "mock_simple", mock_simple, raising=False)

@pytest.fixture
def pypiurls():
    from devpi_server.extpypi import PYPIURL, PYPIURL_SIMPLE
    class PyPIURL:
        def __init__(self):
            self.base = PYPIURL
            self.simple = PYPIURL_SIMPLE
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
        r = self.testapp.get("/%s" % user, {"Accept": "*/json"})
        assert r.status_code == 200
        name = r.json["result"]["username"]
        result = {}
        for index, data in r.json["result"].get("indexes", {}).items():
            result["%s/%s" % (name, index)] = data
        return result

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

    def modify_user(self, user, code=200, password=None, email=None):
        reqdict = {}
        if password:
            reqdict["password"] = password
        if email:
            reqdict["email"] = email
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
            assert r.json["result"]["type"] == "stage"
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
            assert r.json["result"]["type"] == "stage"
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
        indexname = self._getindexname(indexname)
        indexurl = "/" + indexname
        r = self.testapp.get_json(indexurl)
        result = r.json["result"]
        result["custom_data"] = data
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

    def set_pypi_whitelist(self, whitelist, indexname=None):
        indexname = self._getindexname(indexname)
        r = self.testapp.get_json("/%s" % indexname)
        result = r.json["result"]
        if not isinstance(whitelist, list):
            whitelist = whitelist.split(",")
        assert isinstance(whitelist, list)
        result["pypi_whitelist"] = whitelist
        r = self.testapp.patch_json("/%s" % (indexname,), result)
        assert r.status_code == 200

    def set_acl(self, users, acltype="upload", indexname=None):
        indexname = self._getindexname(indexname)
        r = self.testapp.get_json("/%s" % indexname)
        result = r.json["result"]
        if not isinstance(users, list):
            users = users.split(",")
        assert isinstance(users, list)
        result["acl_upload"] = users
        r = self.testapp.patch_json("/%s" % (indexname,), result)
        assert r.status_code == 200

    def get_acl(self, acltype="upload", indexname=None):
        indexname = self._getindexname(indexname)
        r = self.testapp.get_json("/%s" % indexname)
        return r.json["result"].get("acl_" + acltype, None)

    def get_pypi_whitelist(self, indexname=None):
        indexname = self._getindexname(indexname)
        r = self.testapp.get_json("/%s" % indexname)
        return r.json["result"]["pypi_whitelist"]

    def delete_project(self, projectname, code=200, indexname=None,
                       waithooks=False):
        indexname = self._getindexname(indexname)
        r = self.testapp.delete_json("/%s/%s" % (indexname,
                projectname), {}, expect_errors=True)
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
            whitelist = set(self.get_pypi_whitelist(indexname=indexname))
            whitelist.add(metadata["name"])
            self.set_pypi_whitelist(sorted(whitelist), indexname=indexname)
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
            '/%s' % indexname, py.std.json.dumps(req), expect_errors=True)
        assert r.status_code == code
        return r

    def get_release_paths(self, projectname):
        r = self.get_simple(projectname)
        pkg_url = URL(r.request.url)
        paths = [pkg_url.joinpath(link["href"]).path
                 for link in BeautifulSoup(r.body).findAll("a")]
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

    def get_simple(self, projectname, code=200):
        r = self.testapp.get(self.api.simpleindex + projectname,
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

    def set_auth(self, user, password):
        self.auth = (user, password)

    def _gen_request(self, method, url, **kw):
        if self.auth:
            headers = kw.get("headers")
            if not headers:
                headers = kw["headers"] = {}
            headers["X-Devpi-Auth"] = b64encode("%s:%s" % self.auth)
            #print ("setting auth header %r %s %s" % (auth, method, url))
        return super(MyTestApp, self)._gen_request(method, url, **kw)

    def post(self, *args, **kwargs):
        code = kwargs.pop("code", None)
        if code is not None and code >= 300:
            kwargs.setdefault("expect_errors", True)
        r = super(MyTestApp, self).post(*args, **kwargs)
        if code is not None:
            assert r.status_code == code
        return r

    def push(self, url, params=None, **kw):
        kw.setdefault("expect_errors", True)
        return self._gen_request("PUSH", url, params=params, **kw)

    def get(self, *args, **kwargs):
        kwargs.setdefault("expect_errors", True)
        accept = kwargs.pop("accept", None)
        if accept is not None:
            headers = kwargs.setdefault("headers", {})
            headers[str("Accept")] = str(accept)
        return super(MyTestApp, self).get(*args, **kwargs)

    def xget(self, code, *args, **kwargs):
        r = self.get(*args, **kwargs)
        assert r.status_code == code
        return r

    def xdel(self, code, *args, **kwargs):
        kwargs.setdefault("expect_errors", True)
        r = self.delete(*args, **kwargs)
        assert r.status_code == code
        return r


    def get_json(self, *args, **kwargs):
        headers = kwargs.setdefault("headers", {})
        headers["Accept"] = "application/json"
        self.x = 1
        return super(MyTestApp, self).get(*args, **kwargs)




@pytest.fixture
def testapp(request, maketestapp, xom):
    return maketestapp(xom)

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
        self._md5 = py.std.hashlib.md5()

    def pypi_package_link(self, pkgname, md5=True):
        link = "https://pypi.python.org/package/some/%s" % pkgname
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
def dummyrequest():
    from pyramid.testing import DummyRequest, setUp, tearDown
    request = DummyRequest()
    setUp(request=request)
    yield request
    tearDown()

@pytest.fixture
def blank_request():
    from pyramid.request import Request
    def blank_request(*args, **kwargs):
        return Request.blank("/blankpath", *args, **kwargs)
    return blank_request
