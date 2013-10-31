
import base64
import sys
import re
import logging
from webtest.forms import Upload
import webtest
import mimetypes
import mock
import pytest
import py
from devpi_server.main import XOM, parseoptions
from devpi_server.extpypi import XMLProxy

log = logging.getLogger(__name__)

def pytest_addoption(parser):
    parser.addoption("--catchall", action="store_true", default=False,
        help="run bottle apps in catchall mode to see exceptions")
    parser.addoption("--slow", action="store_true", default=False,
        help="run slow tests involving remote services (pypi.python.org)")

@pytest.fixture()
def caplog(caplog):
    """ enrich the pytest-capturelog funcarg. """
    caplog.setLevel(logging.DEBUG)
    def getrecords(msgrex=None):
        if msgrex is not None:
            msgrex = re.compile(msgrex)
        recs = []
        for rec in caplog.records():
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

@pytest.fixture
def xom(request, makexom):
    return makexom([])

@pytest.fixture
def makexom(request, gentmp, httpget):
    def makexom(opts=(), httpget=httpget, proxy=None, mocking=True):
        serverdir = gentmp()
        fullopts = ["devpi-server", "--serverdir", serverdir] + list(opts)
        fullopts = [str(x) for x in fullopts]
        config = parseoptions(fullopts)
        if mocking:
            if proxy is None:
                proxy = mock.create_autospec(XMLProxy)
                proxy.list_packages_with_serial.return_value = {}
            xom = XOM(config, proxy=proxy, httpget=httpget)
            add_extdb_mocks(xom.extdb, httpget)
        else:
            xom = XOM(config)
        request.addfinalizer(xom.shutdown)
        return xom
    return makexom


@pytest.fixture
def maketestapp(request):
    def maketestapp(xom):
        app = xom.create_app(catchall=False, immediatetasks=-1)
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

        def __call__(self, url, allow_redirects=False):
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

        def setextsimple(self, name, text=None, pypiserial=10000, **kw):
            headers = kw.setdefault("headers", {})
            headers["X-PYPI-LAST-SERIAL"] = pypiserial
            return self.mockresponse(pypiurls.simple + name + "/",
                                      text=text, **kw)

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
def extdb(xom):
    return xom.extdb

def add_extdb_mocks(extdb, httpget):
    # add some mocking helpers
    extdb.url2response = httpget.url2response
    def setextsimple(name, text=None, pypiserial=10000, **kw):
        extdb._set_project_serial(name, pypiserial)
        httpget.setextsimple(name, text=text, pypiserial=pypiserial, **kw)
    extdb.setextsimple = setextsimple
    extdb.mock_simple = setextsimple
    extdb.httpget = httpget

@pytest.fixture
def pypiurls():
    from devpi_server.extpypi import PYPIURL_SIMPLE, PYPIURL
    class PyPIURL:
        def __init__(self):
            self.base = PYPIURL
            self.simple = PYPIURL_SIMPLE
    return PyPIURL()

@pytest.fixture
def db(xom):
    from devpi_server.db import DB
    from devpi_server.main import set_default_indexes
    db = DB(xom)
    set_default_indexes(db)
    return db

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

    def getuserlist(self):
        r = self.testapp.get("/", {"indexes": False}, {"Accept": "*/json"})
        assert r.status_code == 200
        return r.json["result"]

    def getindexlist(self, user=None):
        if user is None:
            user = self.testapp.auth[0]
        r = self.testapp.get("/%s/" % user, {"Accept": "*/json"})
        assert r.status_code == 200
        return r.json["result"]

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
            res = r.json["result"]
            assert res["username"] == user
            for name, val in reqdict.items():
                assert res[name] == val

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

    def delete_index(self, indexname, code=201):
        if "/" in indexname:
            user, index = indexname.split("/")
        else:
            user, password = self.testapp.auth
            index = indexname
        r = self.testapp.delete_json("/%s/%s" % (user, index),
                                     expect_errors=True)
        assert r.status_code == code

    def set_uploadtrigger_jenkins(self, triggerurl, indexname=None):
        indexname = self._getindexname(indexname)
        indexurl = "/" + indexname
        r = self.testapp.get_json(indexurl)
        result = r.json["result"]
        result["uploadtrigger_jenkins"] = triggerurl
        r = self.testapp.patch_json(indexurl, result)
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

    def delete_project(self, projectname, code=200, indexname=None):
        indexname = self._getindexname(indexname)
        r = self.testapp.delete_json("/%s/%s" % (indexname,
                projectname), {}, expect_errors=True)
        assert r.status_code == code

    def register_metadata(self, metadata, indexname=None, code=200):
        indexname = self._getindexname(indexname)
        metadata = metadata.copy()
        metadata[":action"] = "submit"
        r = self.testapp.post("/%s/" % indexname, metadata,
                              expect_errors=True)
        assert r.status_code == code

    def upload_file_pypi(self, basename, content,
                         name=None, version=None, indexname=None,
                         register=True,
                         code=200):
        assert py.builtin._isbytes(content)
        indexname = self._getindexname(indexname)
        #name_version = splitbasename(basename, checkarch=False)
        #if not name:
        #    name = name_version[0]
        #if not version:
        #    version = name_version[1]
        if register and code == 200:
            self.register_metadata(dict(name=name, version=version))
        r = self.testapp.post("/%s/" % indexname,
            {":action": "file_upload", "name": name, "version": version,
             "content": Upload(basename, content)}, expect_errors=True)
        assert r.status_code == code


    def upload_doc(self, basename, content, name, version, indexname=None,
                         code=200):
        indexname = self._getindexname(indexname)
        r = self.testapp.post("/%s/" % indexname,
            {":action": "doc_upload", "name": name, "version": version,
             "content": Upload(basename, content)}, expect_errors=True)
        assert r.status_code == code

    def get_simple(self, projectname, code=200):
        r = self.testapp.get(self.api.simpleindex + projectname + "/",
                             expect_errors=True)
        assert r.status_code == code
        return r


from webtest import TestApp as TApp

class MyTestApp(TApp):
    auth = None

    def set_auth(self, user, password):
        self.auth = (user, password)

    def _gen_request(self, method, url, **kw):
        if self.auth:
            headers = kw.get("headers")
            if not headers:
                headers = kw["headers"] = {}
            auth = "%s:%s" % self.auth
            if sys.version_info[0] >= 3:
                res = "Basic " + base64.b64encode(auth.encode("ascii")).decode("ascii")
            else:
                res = "Basic %s" % base64.b64encode(auth)
            #base64.b64encode(("%s:%s" % self.auth).encode("ascii"))
            headers["Authorization"] = res
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
        return self._gen_request("push", url, params=params, **kw)

    def get(self, *args, **kwargs):
        if "expect_errors" not in kwargs:
            kwargs["expect_errors"] = True
        return super(MyTestApp, self).get(*args, **kwargs)

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
                     on_request=None):
        if not url:
            url = "*"
        r = ReqReply(code=code, data=data, headers=headers,
                     on_request=on_request)
        if method is not None:
            method = method.upper()
        self.url2reply[(url, method)] = r
        return r

class ReqReply(HTTPResponse):
    def __init__(self, code, data, headers, on_request):
        if py.builtin._istext(data):
            data = data.encode("utf-8")
        super(ReqReply, self).__init__(body=py.io.BytesIO(data),
                                       status=code,
                                       headers=headers,
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

