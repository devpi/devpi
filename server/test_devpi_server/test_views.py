
import pytest
import py
import webtest
from bs4 import BeautifulSoup
from webtest.forms import Upload
from devpi_server.views import PyPIView
from webtest import TestApp as TApp
from test_db import create_zipfile


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
            print ("setting auth header %r" % auth)
        return super(MyTestApp, self)._gen_request(method, url, **kw)

    def get(self, *args, **kwargs):
        if "expect_errors" not in kwargs:
            kwargs["expect_errors"] = True
        return super(MyTestApp, self).get(*args, **kwargs)

    def get_json(self, *args, **kwargs):
        headers = kwargs.setdefault("headers", {})
        headers["Accept"] = "application/json"
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

def test_index_root(pypiurls, httpget, testapp, xom):
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
    r = testapp.get("/user/name/-api")
    assert r.status_code == 404
    #for name in "pushrelease simpleindex login pypisubmit resultlog".split():
    #    assert name in r.json
    #

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

def test_upload(httpget, db, mapp, testapp):
    mapp.create_and_login_user("user")
    mapp.create_index("name")
    mapp.upload_file("user", "name", "pkg1-2.6.tgz", "123", "pkg1", "2.6")
    r = testapp.get("/user/name/+simple/pkg1/")
    assert r.status_code == 200
    a = getfirstlink(r.text)
    assert "pkg1-2.6.tgz" in a.get("href")

def test_upload_docs_too_large(httpget, db, mapp, testapp):
    from devpi_server.views import MAXDOCZIPSIZE
    mapp.create_and_login_user("user")
    mapp.create_index("name")
    content = "*" * (MAXDOCZIPSIZE + 1)
    mapp.upload_doc_fails("user", "name", "pkg1.zip", content, "pkg1", "2.6")

def test_upload_docs(httpget, db, mapp, testapp):
    mapp.create_and_login_user("user")
    mapp.create_index("name")
    content = create_zipfile({"index.html": "<html/>"})
    mapp.upload_doc("user", "name", "pkg1.zip", content, "pkg1", "2.6")
    r = testapp.get("/user/name/pkg1/+doc/index.html")
    assert r.status_code == 200
    #a = getfirstlink(r.text)
    #assert "pkg1-2.6.tgz" in a.get("href")


class TestLoginBasics:
    def test_wrong_login_format(self, testapp, mapp):
        api = mapp.getapi()
        r = testapp.post(api.login, "qweqweqwe", expect_errors=True)
        assert r.status_code == 400
        r = testapp.post_json(api.login, {"qwelk": ""}, expect_errors=True)
        assert r.status_code == 400

    def test_login_root_default(self, testapp):
        r = testapp.post_json(api.login, {"user": "root", "password": "123"},
                              expect_errors=True)
        assert r.status_code == 401
        assert not testapp.auth
        r = testapp.post_json(api.login, {"user": "root", "password": ""},
                              expect_errors=True)
        assert r.status_code == 200
        assert "password" in r.json
        assert "expiration" in r.json

    def test_login_root_default(self, testapp):
        testapp.set_auth("root", "")
        r = testapp.patch_json("/user", {"password": "123"})
        assert r.status_code == 200

@pytest.fixture
def mapp(testapp):
    return Mapp(testapp)

class Mapp:
    def __init__(self, testapp):
        self.testapp = testapp

    def delete_user(self, user):
        self.testapp.delete_json("/%s" % user)

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

    def login(self, user="root", password=""):
        r = self.testapp.post_json("/+login",
                                  {"user": user, "password": password})
        print "logging in as", user
        self.testapp.set_auth(user, r.json["password"])
        self.auth = user, r.json["password"]

    def login_fails(self, user="root", password=""):
        r = self.testapp.post_json("/+login",
            {"user": user, "password": password}, expect_errors=True)
        assert r.status_code >= 400

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
        self.testapp.auth = (self.testapp.auth[0], r.json["password"])

    def create_user(self, user, password, email="hello@example.com"):
        reqdict = dict(password=password, email=email)
        r = self.testapp.put_json("/%s" % user, reqdict)
        assert r.status_code == 201
        res = r.json["result"]
        assert res["username"] == user
        assert res["email"] == email

    def create_user_fails(self, user, password, email="hello@example.com"):
        with pytest.raises(webtest.AppError) as excinfo:
            self.create_user(user, password)
        assert "409" in excinfo.value.args[0]

    def create_and_login_user(self, user="someuser"):
        self.create_user(user, "123")
        self.login(user, "123")

    def create_index(self, indexname):
        user, password = self.testapp.auth
        r = self.testapp.put_json("/%s/%s" % (user, indexname), {})
        assert r.status_code == 201
        assert r.json["result"]["type"] == "stage"

    def create_project(self, indexname, projectname, code=201):
        user, password = self.testapp.auth
        r = self.testapp.put_json("/%s/%s/hello" % (user, indexname), {},
                expect_errors=True)
        assert r.status_code == code
        if code == 201:
            assert "created" in r.json["message"]

    def delete_user_fails(self, username):
        r = self.testapp.delete_json("/%s" % username, expect_errors=True)
        assert r.status_code == 404

    def upload_file(self, user, index, basename, content, name, version):
        r = self.testapp.post("/%s/%s/" % (user, index),
            {":action": "file_upload", "name": name, "version": version,
             "content": Upload(basename, content)})
        assert r.status_code == 200

    def upload_doc(self, user, index, basename, content, name, version):
        r = self.testapp.post("/%s/%s/" % (user, index),
            {":action": "doc_upload", "name": name, "version": version,
             "content": Upload(basename, content)})
        assert r.status_code == 200

    def upload_doc_fails(self, user, index, basename, content, name, version):
        r = self.testapp.post("/%s/%s/" % (user, index),
            {":action": "doc_upload", "name": name, "version": version,
             "content": Upload(basename, content)}, expect_errors=True)
        assert r.status_code >= 400 and r.status_code < 500


class TestUserThings:
    def test_create_and_delete_user(self, mapp):
        password = "somepassword123123"
        #self.login(testapp)
        #self.login_fails(testapp, "hello", "qweqwe")
        assert "hello" not in mapp.getuserlist()
        mapp.create_user("hello", password)
        mapp.create_user_fails("hello", password)
        assert "hello" in mapp.getuserlist()
        mapp.login_fails("hello", "qweqwe")
        mapp.login("hello", password)
        mapp.delete_user("hello")
        mapp.login_fails("hello", password)
        assert "hello" not in mapp.getuserlist()

    def test_delete_not_existent(self, mapp):
        mapp.login("root", "")
        mapp.delete_user_fails("qlwkje")

    def test_password_setting_admin(self, mapp):
        mapp.login("root", "")
        mapp.change_password("root", "p1oi2p3i")
        mapp.login("root", "p1oi2p3i")


class TestIndexOnlyWeb:
    def test_create_project(self, mapp):
        mapp.create_and_login_user()
        mapp.create_index("dev")
        mapp.create_project("dev", "hello")
        mapp.create_project("dev", "hello", code=409)


class TestIndexThings:

    def test_create_index(self, mapp):
        mapp.create_and_login_user()
        indexname = mapp.auth[0] + "/dev"
        assert indexname not in mapp.getindexlist()
        mapp.create_index("dev")
        assert indexname in mapp.getindexlist()


    @pytest.mark.parametrize(["input", "expected"], [
        ({},
          dict(type="stage", volatile=True, bases=["root/dev", "root/pypi"])),
        ({"volatile": "False"},
          dict(type="stage", volatile=False, bases=["root/dev", "root/pypi"])),
        ({"volatile": "False", "bases": "root/pypi"},
          dict(type="stage", volatile=False, bases=["root/pypi"])),
    ])
    def test_kvdict(self, input, expected):
        from devpi_server.views import getkvdict_index
        result = getkvdict_index(input)
        assert result == expected

