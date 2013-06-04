
import re
import logging
import mimetypes
import pytest
import py
from devpi_server.main import XOM, add_keys


log = logging.getLogger(__name__)

def pytest_addoption(parser):
    parser.addoption("--catchall", action="store_true", default=False,
        help="run bottle apps in catchall mode to see exceptions")

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
def xom_notmocked(request):
    from devpi_server.main import parseoptions, XOM
    config = parseoptions(["devpi-server"])
    xom = XOM(config)
    request.addfinalizer(xom.shutdown)
    return xom

@pytest.fixture
def xom(request, keyfs, filestore, httpget):
    from devpi_server.main import parseoptions, XOM
    from devpi_server.extpypi import ExtDB
    config = parseoptions(["devpi-server"])
    xom = XOM(config)
    xom.keyfs = keyfs
    xom.releasefilestore = filestore
    xom.httpget = httpget
    xom.extdb = ExtDB(xom=xom)
    xom.extdb.setextsimple = httpget.setextsimple
    xom.extdb.url2response = httpget.url2response
    request.addfinalizer(xom.shutdown)
    return xom

@pytest.fixture
def httpget(pypiurls):
    url2response = {}
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
                    xself.url = url
                    xself.allow_redirects = allow_redirects
                def __repr__(xself):
                    return "<mockresponse %s url=%s>" % (xself.status_code,
                                                         xself.url)
            r = mockresponse(url)
            log.debug("returning %s", r)
            return r

        def mockresponse(self, url, **kw):
            if "status_code" not in kw:
                kw["status_code"] = 200
            log.debug("set mocking response %s %s", url, kw)
            self.url2response[url] = kw

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
def filestore(keyfs):
    from devpi_server.filestore import ReleaseFileStore
    return ReleaseFileStore(keyfs)

@pytest.fixture
def keyfs(tmpdir):
    from devpi_server.keyfs import KeyFS
    keyfs = KeyFS(tmpdir.join("keyfs"))
    add_keys(keyfs)
    return keyfs

@pytest.fixture
def extdb(xom):
    return xom.extdb

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
