
import pytest
import py
import webtest
from bs4 import BeautifulSoup
from webtest.forms import Upload
from devpi_server.views import LOGINCOOKIE
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
            auth = ("%s:%s" % self.auth).encode("base64")
            headers["Authorization"] = "Basic %s" % auth
            print ("setting auth header %r" % auth)
        return super(MyTestApp, self)._gen_request(method, url, **kw)

    def get(self, *args, **kwargs):
        if "expect_errors" not in kwargs:
            kwargs["expect_errors"] = True
        return super(MyTestApp, self).get(*args, **kwargs)



def getfirstlink(text):
    return BeautifulSoup(text).findAll("a")[0]


@pytest.fixture
def testapp(request, xom):
    app = xom.create_app(catchall=False) # request.config.option.catchall)
    return MyTestApp(app)

def test_simple_project(pypiurls, httpget, testapp):
    name = "qpwoei"
    r = testapp.get("/ext/pypi/simple/" + name)
    assert r.status_code == 404
    path = "/%s-1.0.zip" % name
    httpget.setextsimple(name, text='<a href="%s"/>' % path)
    r = testapp.get("/ext/pypi/simple/%s" % name)
    assert r.status_code == 200
    links = BeautifulSoup(r.text).findAll("a")
    assert len(links) == 1
    assert links[0].get("href").endswith(path)

def test_simple_list(pypiurls, httpget, testapp):
    httpget.setextsimple("hello1", text="<html/>")
    httpget.setextsimple("hello2", text="<html/>")
    assert testapp.get("/ext/pypi/simple/hello1").status_code == 200
    assert testapp.get("/ext/pypi/simple/hello2").status_code == 200
    assert testapp.get("/ext/pypi/simple/hello3").status_code == 404
    r = testapp.get("/ext/pypi/simple/")
    assert r.status_code == 200
    links = BeautifulSoup(r.text).findAll("a")
    assert len(links) == 2
    hrefs = [a.get("href") for a in links]
    assert hrefs == ["hello1/", "hello2/"]

def test_index_root(pypiurls, httpget, testapp, xom):
    xom.db.create_stage("user/index", bases=("ext/pypi",))
    r = testapp.get("/user/index/")
    assert r.status_code == 200

@pytest.mark.parametrize("code", [-1, 500, 501, 502, 503])
def test_upstream_not_reachable(pypiurls, httpget, testapp, xom, code):
    name = "whatever%d" % (code + 1)
    httpget.setextsimple(name, status_code = code)
    r = testapp.get("/ext/pypi/simple/%s" % name)
    assert r.status_code == 502

def test_pkgserv(pypiurls, httpget, testapp):
    httpget.setextsimple("package", '<a href="/package-1.0.zip" />')
    httpget.setextfile("/package-1.0.zip", "123")
    r = testapp.get("/ext/pypi/simple/package")
    assert r.status_code == 200
    r = testapp.get(getfirstlink(r.text).get("href"))
    assert r.body == "123"

def test_apiconfig(httpget, testapp):
    r = testapp.get("/user/name/-api")
    assert r.status_code == 200
    for name in "pushrelease simpleindex login pypisubmit resultlog".split():
        assert name in r.json

def test_upload(httpget, db, mapp, testapp):
    mapp.create_and_login_user("user")
    mapp.create_index("name")
    BytesIO = py.io.BytesIO
    r = testapp.post("/user/name/pypi/",
        {":action": "file_upload", "name": "pkg1", "version": "2.6",
         "content": Upload("pkg1-2.6.tgz", "123")})
    assert r.status_code == 200
    r = testapp.get("/user/name/simple/pkg1/")
    assert r.status_code == 200
    a = getfirstlink(r.text)
    assert "pkg1-2.6.tgz" in a.get("href")


class TestAdminLogin:
    def test_wrong_login_format(self, testapp):
        r = testapp.post("/login", "qweqweqwe", expect_errors=True)
        assert r.status_code == 400
        r = testapp.post_json("/login", {"qwelk": ""}, expect_errors=True)
        assert r.status_code == 400

    def test_login_admin_default(self, testapp):
        r = testapp.post_json("/login", {"user": "admin", "password": "123"},
                              expect_errors=True)
        assert r.status_code == 401
        assert not testapp.auth
        r = testapp.post_json("/login", {"user": "admin", "password": ""},
                              expect_errors=True)
        assert r.status_code == 200
        assert "password" in r.json
        assert "expiration" in r.json

@pytest.fixture
def mapp(testapp):
    return Mapp(testapp)

class Mapp:
    def __init__(self, testapp):
        self.testapp = testapp

    def delete_user(self, user):
        self.testapp.delete_json("/%s" % user)

    def login(self, user="admin", password=""):
        r = self.testapp.post_json("/login",
                                  {"user": user, "password": password})
        print "logging in as", user
        self.testapp.set_auth(user, r.json["password"])

    def login_fails(self, user="admin", password=""):
        r = self.testapp.post_json("/login",
            {"user": user, "password": password}, expect_errors=True)
        assert r.status_code >= 400

    def getuserlist(self):
        r = self.testapp.get("/", {"indexes": False}, {"Accept": "*/json"})
        return r.json

    def change_password(self, user, password):
        auth = self.testapp.auth
        r = self.testapp.patch_json("/%s" % user, dict(password=password))
        self.testapp.auth = (self.testapp.auth[0], r.json["password"])

    def create_user(self, user, password):
        self.testapp.put_json("/%s" % user, dict(password=password))

    def create_and_login_user(self, user="someuser"):
        self.create_user(user, "123")
        self.login(user, "123")

    def create_index(self, indexname):
        user, password = self.testapp.auth
        r = self.testapp.put_json("/%s/%s" % (user, indexname))
        assert r.status_code == 201
        assert r.json["type"] == "private"



class TestUserThings:
    def test_password_setting_admin(self, mapp):
        mapp.login("admin", "")
        mapp.change_password("admin", "p1oi2p3i")
        mapp.login("admin", "p1oi2p3i")

    def test_create_and_delete_user(self, mapp):
        password = "somepassword123123"
        #self.login(testapp)
        #self.login_fails(testapp, "hello", "qweqwe")
        mapp.create_user("hello", password)
        with pytest.raises(webtest.AppError) as excinfo:
            mapp.create_user("hello", password)
        assert "409" in excinfo.value.args[0]
        mapp.login_fails("hello", "qweqwe")
        mapp.login("hello", password)
        mapp.delete_user("hello")
        mapp.login_fails("hello", password)

    def test_create_and_list_user(self, mapp):
        d = mapp.getuserlist()
        users = d["users"]
        assert set(users) == set("admin int ext".split())

    def test_delete_not_existent(self, mapp):
        mapp.login()
        r = mapp.testapp.delete_json("/qlwkje", expect_errors=True)
        assert r.status_code == 404


class TestIndexThings:

    def test_create_index(self, mapp):
        mapp.create_and_login_user()
        mapp.create_index("dev")
