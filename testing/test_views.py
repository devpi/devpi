
import pytest
from bs4 import BeautifulSoup

def getfirstlink(text):
    return BeautifulSoup(text).findAll("a")[0]

@pytest.fixture
def httpget(request, xom, httpget, monkeypatch):
    print "patching httpget"
    xom.httpget = httpget
    assert xom.httpget == httpget
    return httpget


@pytest.fixture
def testapp(request, xom):
    from webtest import TestApp
    app = xom.create_app(catchall=request.config.option.catchall)
    testapp = TestApp(app)
    oldget = testapp.get
    testapp.get = lambda path, expect_errors=True: \
                        oldget(path, expect_errors=expect_errors)
    return testapp

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
