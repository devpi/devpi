
import pytest
import py
import webtest
import requests, json
from bs4 import BeautifulSoup
from webtest.forms import Upload
from devpi_server.views import *
import devpi_server.views
from webtest import TestApp as TApp
from test_db import create_zipfile
from mock import Mock

from .functional import TestUserThings, TestIndexThings


class MyTestApp(TApp):
    auth = None

    def set_auth(self, user, password):
        self.auth = (user, password)

    def _gen_request(self, method, url, **kw):
        if self.auth:
            headers = kw.get("headers")
            if not headers:
                headers = kw["headers"] = {}
            auth = ("%s:%s" % self.auth).encode("base64")
            headers["Authorization"] = "Basic %s" % auth
            #print ("setting auth header %r %s %s" % (auth, method, url))
        return super(MyTestApp, self)._gen_request(method, url, **kw)

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


def getfirstlink(text):
    return BeautifulSoup(text).findAll("a")[0]


@pytest.fixture
def testapp(request, xom):
    app = xom.create_app(catchall=False, immediatetasks=-1)
    return MyTestApp(app)

def test_simple_project(pypiurls, httpget, testapp):
    name = "qpwoei"
    r = testapp.get("/root/pypi/+simple/" + name)
    assert r.status_code == 404
    path = "/%s-1.0.zip" % name
    httpget.setextsimple(name, text='<a href="%s"/>' % path)
    r = testapp.get("/root/pypi/+simple/%s" % name)
    assert r.status_code == 200
    links = BeautifulSoup(r.text).findAll("a")
    assert len(links) == 1
    assert links[0].get("href").endswith(path)

def test_simple_url_longer_triggers_404(testapp):
    assert testapp.get("/root/pypi/+simple/pytest/1.0/").status_code == 404
    assert testapp.get("/root/pypi/+simple/pytest/1.0").status_code == 404

def test_simple_project_pypi_egg(pypiurls, httpget, testapp):
    httpget.setextsimple("py",
        """<a href="http://bb.org/download/py.zip#egg=py-dev" />""")
    r = testapp.get("/root/pypi/+simple/py/")
    assert r.status_code == 200
    links = BeautifulSoup(r.text).findAll("a")
    assert len(links) == 1
    r = testapp.get("/root/pypi/")
    assert r.status_code == 200

def test_simple_list(pypiurls, httpget, testapp):
    httpget.setextsimple("hello1", text="<html/>")
    httpget.setextsimple("hello2", text="<html/>")
    assert testapp.get("/root/pypi/+simple/hello1").status_code == 200
    assert testapp.get("/root/pypi/+simple/hello2").status_code == 200
    assert testapp.get("/root/pypi/+simple/hello3").status_code == 404
    r = testapp.get("/root/pypi/+simple/")
    assert r.status_code == 200
    links = BeautifulSoup(r.text).findAll("a")
    assert len(links) == 2
    hrefs = [a.get("href") for a in links]
    assert hrefs == ["hello1/", "hello2/"]

def test_indexroot(pypiurls, httpget, testapp, xom):
    xom.db.create_stage("user/index", bases=("root/pypi",))
    r = testapp.get("/user/index/")
    assert r.status_code == 200

@pytest.mark.parametrize("code", [-1, 500, 501, 502, 503])
def test_upstream_not_reachable(pypiurls, httpget, testapp, xom, code):
    name = "whatever%d" % (code + 1)
    httpget.setextsimple(name, status_code = code)
    r = testapp.get("/root/pypi/+simple/%s" % name)
    assert r.status_code == 502

def test_pkgserv(pypiurls, httpget, testapp):
    httpget.setextsimple("package", '<a href="/package-1.0.zip" />')
    httpget.setextfile("/package-1.0.zip", "123")
    r = testapp.get("/root/pypi/+simple/package/")
    assert r.status_code == 200
    r = testapp.get(getfirstlink(r.text).get("href"))
    assert r.body == "123"

def test_apiconfig(httpget, testapp):
    r = testapp.get("/user/name/+api")
    assert r.status_code == 404
    r = testapp.get("/root/dev/+api")
    assert r.status_code == 200
    assert r.json["result"]["pypisubmit"]
    assert r.json["result"]["bases"] == "root/pypi/"
    r = testapp.get("/root/pypi/+api")
    assert r.status_code == 200
    assert not "pypisubmit" in r.json["result"]

    #for name in "pushrelease simpleindex login pypisubmit resultlog".split():
    #    assert name in r.json
    #
    #
def test_root_pypi(httpget, testapp):
    r = testapp.get("/root/pypi/")
    assert r.status_code == 200

def test_register_metadata_and_get_description(httpget, db, mapp, testapp):
    mapp.create_and_login_user("user")
    mapp.create_index("name")
    api = mapp.getapi("user/name")
    metadata = {"name": "pkg1", "version": "1.0", ":action": "submit",
                "description": "hello world"}
    r = testapp.post(api.pypisubmit, metadata)
    assert r.status_code == 200
    r = testapp.get_json("/user/name/pkg1/1.0/")
    assert r.status_code == 200
    assert "hello world" in r.json["result"]["description"]
    r = testapp.get_json("/user/name/pkg1/")
    assert r.status_code == 200
    assert "1.0" in r.json["result"]

def test_push_non_existent(httpget, db, mapp, testapp, monkeypatch):
    # check that push from non-existent index results in 404
    req = dict(name="pkg5", version="2.6", targetindex="user2/dev")
    r = testapp.push("/user2/dev/", json.dumps(req), expect_errors=True)
    assert r.status_code == 404
    mapp.create_and_login_user("user1", "1")
    mapp.create_index("dev")

    # check that push to non-existent target index results in 404
    r = testapp.push("/user1/dev/", json.dumps(req), expect_errors=True)
    assert r.status_code == 404

    mapp.create_and_login_user("user2")
    mapp.create_index("dev", indexconfig=dict(acl_upload=["user2"]))
    mapp.login("user1", "1")
    # check that push of non-existent release results in 404
    r = testapp.push("/user1/dev/", json.dumps(req), expect_errors=True)
    assert r.status_code == 404
    #
    mapp.upload_file_pypi(
            "user1", "dev", "pkg5-2.6.tgz", "123", "pkg5", "2.6")
    # check that push to non-authoried existent target index results in 401
    r = testapp.push("/user1/dev/", json.dumps(req), expect_errors=True)
    assert r.status_code == 401

def test_upload_and_push_internal(httpget, db, mapp, testapp, monkeypatch):
    mapp.create_user("user1", "1")
    mapp.create_and_login_user("user2")
    mapp.create_index("prod", indexconfig=dict(acl_upload=["user1", "user2"]))
    mapp.create_index("dev", indexconfig=dict(acl_upload=["user2"]))
    print mapp.getjson("/user2/prod")

    mapp.login("user1", "1")
    mapp.create_index("dev")
    mapp.upload_file_pypi(
            "user1", "dev", "pkg1-2.6.tgz", "123", "pkg1", "2.6")

    # check that push is authorized and executed towards user2/prod index
    req = dict(name="pkg1", version="2.6", targetindex="user2/prod")
    r = testapp.push("/user1/dev/", json.dumps(req))
    assert r.status_code == 200
    r = testapp.get_json("/user2/prod/pkg1/2.6")
    assert r.status_code == 200
    relpath = r.json["result"]["+files"]["pkg1-2.6.tgz"]
    assert relpath == "user2/prod/pkg1/2.6/pkg1-2.6.tgz"

def test_upload_and_push_remote_ok(httpget, db, mapp, testapp, monkeypatch):
    mapp.create_and_login_user("user")
    mapp.create_index("name")
    mapp.upload_file_pypi(
            "user", "name", "pkg1-2.6.tgz", "123", "pkg1", "2.6")
    r = testapp.get("/user/name/+simple/pkg1/")
    assert r.status_code == 200
    a = getfirstlink(r.text)
    assert "pkg1-2.6.tgz" in a.get("href")

    # get root index page
    r = testapp.get("/user/name/")
    assert r.status_code == 200

    # push
    req = dict(name="pkg1", version="2.6", posturl="whatever",
               username="user", password="password")
    rec = []
    def recpost(url, data, auth, files=None):
        rec.append((url, data, auth, files))
        class r:
            status_code = 200
        return r
    monkeypatch.setattr(requests, "post", recpost)
    body = json.dumps(req)
    r = testapp.request("/user/name/", method="push", body=body,
                        expect_errors=True)
    assert r.status_code == 200
    assert len(rec) == 2
    assert rec[0][0] == "whatever"
    assert rec[1][0] == "whatever"

    # push with error
    def posterror(url, data, auth, files=None):
        class r:
            status_code = 500
        return r
    monkeypatch.setattr(requests, "post", posterror)
    r = testapp.request("/user/name/", method="push", body=body,
                        expect_errors=True)
    assert r.status_code == 502
    result = r.json["result"]
    assert len(result) == 1
    assert result[0][0] == 500

def test_upload_and_push_egg(httpget, db, mapp, testapp, monkeypatch):
    mapp.create_and_login_user("user")
    mapp.create_index("name")
    mapp.upload_file_pypi(
            "user", "name", "pkg2-1.0-py27.egg", "123", "pkg2", "1.0")
    r = testapp.get("/user/name/+simple/pkg2/")
    assert r.status_code == 200
    a = getfirstlink(r.text)
    assert "pkg2-1.0-py27.egg" in a.get("href")

    # push
    req = dict(name="pkg2", version="1.0", posturl="whatever",
               username="user", password="password")
    rec = []
    def recpost(url, data, auth, files=None):
        rec.append((url, data, auth, files))
        class r:
            status_code = 200
        return r
    monkeypatch.setattr(requests, "post", recpost)
    r = testapp.push("/user/name/", json.dumps(req))
    assert r.status_code == 200
    assert len(rec) == 2
    assert rec[0][0] == "whatever"
    assert rec[1][0] == "whatever"

def test_upload_and_remove_project(httpget, db, mapp, testapp, monkeypatch):
    mapp.create_and_login_user("user")
    mapp.create_index("name")
    r = testapp.delete("/user/name/pkg1/", expect_errors=True)
    assert r.status_code == 404
    mapp.upload_file_pypi(
            "user", "name", "pkg1-2.6.tgz", "123", "pkg1", "2.6")
    r = testapp.get("/user/name/+simple/pkg1/")
    assert r.status_code == 200
    r = testapp.delete("/user/name/pkg1/")
    assert r.status_code == 200
    data = mapp.getjson("/user/name/pkg1/")
    #assert data["status"] == 404
    assert not data["result"]

def test_upload_with_acl(httpget, db, mapp, testapp, monkeypatch):
    mapp.login("root")
    mapp.change_password("root", "123")
    mapp.create_user("user", "123")

    mapp.create_and_login_user("i1", "456")
    mapp.create_index("dev")

    mapp.login("user", "123")
    # user cannot write to index now
    mapp.upload_file_pypi(
            "i1", "dev", "pkg1-2.6.tgz", "123", "pkg1", "2.6", code=403)
    mapp.login("i1", "456")
    mapp.set_acl("i1/dev", ["user"])
    mapp.login("user", "123")
    mapp.upload_file_pypi(
            "i1", "dev", "pkg1-2.6.tgz", "123", "pkg1", "2.6")

def test_upload_with_jenkins(db, mapp, testapp, monkeypatch):
    mapp.create_and_login_user("i1", "456")
    mapp.create_index("dev")
    mapp.set_uploadtrigger_jenkins("i1/dev", "http://x.com/{pkgname}")
    from devpi_server import views
    post_mock = Mock(autospec=requests.post)
    monkeypatch.setattr(views.requests, "post", post_mock)
    mapp.upload_file_pypi(
            "i1", "dev", "pkg1-2.6.tgz", "123", "pkg1", "2.6", code=200)
    assert post_mock.call_count == 1
    args = post_mock.call_args
    assert args[0][0] == "http://x.com/pkg1"
    assert args[1]["data"]["Submit"] == "Build"

def test_upload_and_testdata(db, mapp, testapp, monkeypatch):
    api = mapp.getapi()
    from test_devpi_server.example import tox_result_data
    mapp.create_and_login_user("i1", "456")
    mapp.create_index("dev")
    mapp.upload_file_pypi(
            "i1", "dev", "pkg1-2.6.tgz", "123", "pkg1", "2.6", code=200)
    r = testapp.post_json(api.resultlog, tox_result_data)
    path = r.json["result"]
    assert r.status_code == 200
    r = testapp.get(path)
    assert r.status_code == 200

def test_upload_and_remove_project_version(httpget, db,
                                           mapp, testapp, monkeypatch):
    mapp.create_and_login_user("user")
    mapp.create_index("name")
    r = testapp.delete("/user/name/pkg1/", expect_errors=True)
    assert r.status_code == 404
    mapp.upload_file_pypi(
            "user", "name", "pkg1-2.6.tgz", "123", "pkg1", "2.6")
    mapp.upload_file_pypi(
            "user", "name", "pkg1-2.7.tgz", "123", "pkg1", "2.7")
    r = testapp.get("/user/name/+simple/pkg1/")
    assert r.status_code == 200
    r = testapp.delete("/user/name/pkg1/1.0", expect_errors=True)
    assert r.status_code == 404
    r = testapp.delete("/user/name/pkg1/2.6/")
    assert r.status_code == 200
    assert mapp.getjson("/user/name/pkg1/")["result"]
    assert testapp.delete("/user/name/pkg1/2.7").status_code == 200
    #assert mapp.getjson("/user/name/pkg1/")["status"] == 404
    assert not mapp.getjson("/user/name/pkg1/")["result"]

def test_upload_and_access_releasefile_meta(httpget, db,
                                           mapp, testapp, monkeypatch):
    mapp.create_and_login_user("user")
    mapp.create_index("name")
    mapp.upload_file_pypi(
            "user", "name", "pkg5-2.6.tgz", "123", "pkg1", "2.6")
    json = mapp.getjson("/user/name/pkg5/")
    href = json["result"]["2.6"]["+files"].values()[0]
    pkgmeta = mapp.getjson("/" + href)
    assert pkgmeta["type"] == "releasefilemeta"
    assert pkgmeta["result"]["size"] == "3"

def test_upload_pypi_fails(httpget, db, mapp, testapp):
    mapp.upload_file_pypi(
            "root", "pypi", "pkg1-2.6.tgz", "123", "pkg1", "2.6", code=404)

def test_delete_pypi_fails(httpget, db, mapp, testapp):
    r = testapp.delete("/root/pypi/pytest/2.3.5", expect_errors=True)
    assert r.status_code == 405
    r = testapp.delete("/root/pypi/pytest", expect_errors=True)
    assert r.status_code == 405

def test_upload_docs_too_large(httpget, db, mapp, testapp):
    from devpi_server.views import MAXDOCZIPSIZE
    mapp.create_and_login_user("user")
    mapp.create_index("name")
    content = "*" * (MAXDOCZIPSIZE + 1)
    mapp.upload_doc("user", "name", "pkg1.zip", content, "pkg1", "2.6",
                    code=413)

def test_upload_docs(httpget, db, mapp, testapp):
    mapp.create_and_login_user("user")
    mapp.create_index("name")
    content = create_zipfile({"index.html": "<html/>"})
    mapp.upload_doc("user", "name", "pkg1.zip", content, "pkg1", "2.6")
    r = testapp.get("/user/name/pkg1/+doc/index.html")
    assert r.status_code == 200
    #a = getfirstlink(r.text)
    #assert "pkg1-2.6.tgz" in a.get("href")

def test_wrong_login_format(testapp, mapp):
    api = mapp.getapi()
    r = testapp.post(api.login, "qweqweqwe", expect_errors=True)
    assert r.status_code == 400
    r = testapp.post_json(api.login, {"qwelk": ""}, expect_errors=True)
    assert r.status_code == 400


@pytest.fixture
def mapp(testapp):
    return Mapp(testapp)

class Mapp:
    def __init__(self, testapp):
        self.testapp = testapp

    def delete_user(self, user, code=200):
        r = self.testapp.delete_json("/%s" % user, expect_errors=True)
        assert r.status_code == code

    def getapi(self, relpath="/"):
        path = relpath.strip("/")
        if not path:
            path = "/+api"
        else:
            path = "/%s/+api" % path
        r = self.testapp.get(path)
        assert r.status_code == 200
        class API:
            def __init__(self):
                self.__dict__.update(r.json["result"])
        return API()

    def login(self, user="root", password="", code=200):
        api = self.getapi()
        r = self.testapp.post_json(api.login,
                                  {"user": user, "password": password},
                                  expect_errors=True)
        assert r.status_code == code
        if code == 200:
            self.testapp.set_auth(user, r.json["password"])
            self.auth = user, r.json["password"]

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
        auth = self.testapp.auth
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

    def getjson(self, path, code=200):
        r = self.testapp.get_json(path, {}, expect_errors=True)
        assert r.status_code == code
        return r.json

    def create_index(self, indexname, indexconfig=None, code=200):
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
        if code in (400,):
            return r.json["message"]

    def set_uploadtrigger_jenkins(self, indexname, triggerurl):
        indexurl = "/" + indexname
        r = self.testapp.get_json(indexurl)
        result = r.json["result"]
        result["uploadtrigger_jenkins"] = triggerurl
        r = self.testapp.patch_json(indexurl, result)
        assert r.status_code == 200

    def set_acl(self, indexname, users, acltype="upload"):
        r = self.testapp.get_json("/%s" % indexname)
        result = r.json["result"]
        if not isinstance(users, list):
            users = users.split(",")
        assert isinstance(users, list)
        result["acl_upload"] = users
        r = self.testapp.patch_json("/%s" % (indexname,), result)
        assert r.status_code == 200

    def get_acl(self, indexname, acltype="upload"):
        r = self.testapp.get_json("/%s" % indexname)
        return r.json["result"].get("acl_" + acltype, None)

    def create_project(self, indexname, projectname, code=201):
        user, password = self.testapp.auth
        r = self.testapp.put_json("/%s/%s/hello" % (user, indexname), {},
                expect_errors=True)
        assert r.status_code == code
        if code == 201:
            assert "created" in r.json["message"]

    def upload_file_pypi(self, user, index, basename, content,
                         name, version, code=200):
        r = self.testapp.post("/%s/%s/" % (user, index),
            {":action": "file_upload", "name": name, "version": version,
             "content": Upload(basename, content)}, expect_errors=True)
        assert r.status_code == code

    def upload_doc(self, user, index, basename, content, name, version,
                         code=200):

        r = self.testapp.post("/%s/%s/" % (user, index),
            {":action": "doc_upload", "name": name, "version": version,
             "content": Upload(basename, content)}, expect_errors=True)
        assert r.status_code == code


@pytest.mark.parametrize(["input", "expected"], [
    ({},
      dict(type="stage", volatile=True, bases=["root/dev"])),
    ({"volatile": "False"},
      dict(type="stage", volatile=False, bases=["root/dev"])),
    ({"volatile": "False", "bases": "root/pypi"},
      dict(type="stage", volatile=False, bases=["root/pypi"])),
    ({"volatile": "False", "bases": ["root/pypi"]},
      dict(type="stage", volatile=False, bases=["root/pypi"])),
    ({"volatile": "False", "bases": ["root/pypi"], "acl_upload": ["hello"]},
      dict(type="stage", volatile=False, bases=["root/pypi"],
           acl_upload=["hello"])),
])
def test_kvdict(input, expected):
    from devpi_server.views import getkvdict_index
    result = getkvdict_index(input)
    assert result == expected

def test_get_outside_url():
    url = get_outside_url({"X-outside-url": "http://outside.com"}, None)
    assert url == "http://outside.com/"
    url = get_outside_url({"X-outside-url": "http://outside.com"},
                          "http://outside2.com")
    assert url == "http://outside2.com/"
    url = get_outside_url({"Host": "outside3.com"}, None)
    assert url == "http://outside3.com/"

class Test_getjson:
    @pytest.fixture
    def abort_calls(self, monkeypatch):
        l = []
        def recorder(*args, **kwargs):
            l.append((args, kwargs))
            raise SystemExit(1)
        monkeypatch.setattr(devpi_server.views, "abort", recorder)
        return l

    def test_getjson(self):
        class request:
            body = py.io.BytesIO(json.dumps({"hello": "world"}))
        assert getjson(request)["hello"] == "world"

    def test_getjson_error(self, abort_calls):
        class request:
            body = py.io.BytesIO("123 123")
        with pytest.raises(SystemExit):
            getjson(request)
        assert abort_calls[0][0][0] == 400

    def test_getjson_wrong_keys(self, abort_calls):
        class request:
            body = py.io.BytesIO(json.dumps({"k1": "v1", "k2": "v2"}))
        with pytest.raises(SystemExit):
            getjson(request, allowed_keys=["k1", "k3"])
        assert abort_calls[0][0][0] == 400


class TestAuth:
    @pytest.fixture
    def auth(self, db):
        from devpi_server.views import Auth
        return Auth(db, "qweqwe")

    def test_no_auth(self, auth):
        assert auth.get_auth_user(None) is None

    def test_auth_direct(self, db, auth):
        db.user_create("user", password="world")
        assert auth.get_auth_user(("user", "world")) == "user"

    def test_proxy_auth(self, db, auth):
        db.user_create("user", password="world")
        assert auth.new_proxy_auth("user", "wrongpass") is None
        assert auth.new_proxy_auth("uer", "wrongpass") is None
        res = auth.new_proxy_auth("user", "world")
        assert "password" in res and "expiration" in res
        assert auth.get_auth_user(("user", res["password"]))

    def test_proxy_auth_expired(self, db, auth, monkeypatch):
        user, password = "user", "world"

        db.user_create(user, password)
        proxy = auth.new_proxy_auth(user, password)

        def r(*args): raise py.std.itsdangerous.SignatureExpired("123")
        monkeypatch.setattr(auth.signer, "unsign", r)

        newauth = (user, proxy["password"])
        res = auth.get_auth_user(newauth, raising=False)
        assert res is None
        with pytest.raises(auth.Expired):
            auth.get_auth_user(newauth)

