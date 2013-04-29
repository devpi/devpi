
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
    return TestApp(app)

def test_simple_project(pypiurls, httpget, testapp):
    name = "qpwoei"
    r = testapp.get("/ext/pypi/" + name, expect_errors=True)
    assert r.status_code == 404
    path = "/%s-1.0.zip" % name
    httpget.setextsimple(name, text='<a href="%s"/a>' % path)
    r = testapp.get("/ext/pypi/%s" % name)
    assert r.status_code == 200
    links = BeautifulSoup(r.text).findAll("a")
    assert len(links) == 1
    assert links[0].get("href").endswith(path)

@pytest.mark.parametrize("code", [-1, 500, 501, 502, 503])
def test_upstream_not_reachable(pypiurls, httpget, testapp, xom, code):
    name = "whatever%d" % (code + 1)
    httpget.setextsimple(name, status_code = code)
    r = testapp.get("/ext/pypi/%s" % name, expect_errors=True)
    assert r.status_code == 502

def test_pkgserv(pypiurls, httpget, testapp):
    httpget.setextsimple("package", '<a href="/package-1.0.zip" />')
    httpget.setextfile("/package-1.0.zip", "123")
    r = testapp.get("/ext/pypi/package")
    assert r.status_code == 200
    r = testapp.get(getfirstlink(r.text).get("href"))
    assert r.body == "123"
