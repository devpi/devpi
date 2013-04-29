
from devpi_server.main import XOM

import pytest
import py
import re
import logging

import mimetypes

log = logging.getLogger(__name__)

def pytest_addoption(parser):
    parser.addoption("--catchall", action="store_true", default=False,
        help="run bottle apps in catchall mode to see exceptions")

@pytest.fixture()
def caplog(caplog):
    """ shadow the pytest-capturelog funcarg to provide some defaults. """
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

@pytest.fixture(scope="session")
def redis(xprocess):
    """ return a session-wide StrictRedis connection which is connected
    to an externally started redis server instance
    (through the xprocess plugin)"""
    redis = pytest.importorskip("redis", "2.7.2")
    conftemplate = py.path.local(__file__).dirpath("redis.conf.template")
    assert conftemplate.check()
    redispath = py.path.local.sysfind("redis-server")
    if not redispath:
        pytest.skip("command not found: redis-server")
    port = 6400
    def prepare_redis(cwd):
        templatestring = conftemplate.read()
        content = templatestring.format(libredis=cwd,
                          port=port, pidfile=cwd.join("_pid_from_redis"))
        cwd.join("redis.conf").write(content)
        return (".*ready to accept connections on port %s.*" % port,
                ["redis-server", "redis.conf"])

    redislogfile = xprocess.ensure("redis", prepare_redis)
    client = redis.StrictRedis(port=port)
    client.port = port
    return client

@pytest.fixture(autouse=True)
def clean_redis(request):
    if "redis" in request.fixturenames:
    #if request.cls and getattr(request.cls, "cleanredis", False):
        redis = request.getfuncargvalue("redis")
        redis.flushdb()

@pytest.fixture
def xom(request, redis):
    from devpi_server.main import parseoptions, XOM
    config = parseoptions(["devpi-server", "--redisport", str(redis.port)])
    xom = XOM(config)
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

        def setextsimple(self, name, text=None, **kw):
            return self.mockresponse(pypiurls.simple + name + "/",
                                      text=text, **kw)

        def setextfile(self, path, content, **kw):
            headers = {"content-length": len(content),
                       "content-type": mimetypes.guess_type(path),
                       "last-modified": "today",}
            if path.startswith("/") and pypiurls.base.endswith("/"):
                path = path.lstrip("/")
            def iter_content(chunksize):
                yield content
            return self.mockresponse(pypiurls.base + path,
                                      iter_content=iter_content,
                                      headers=headers,
                                      **kw)


    return MockHTTPGet()

@pytest.fixture
def filestore(redis, tmpdir):
    from devpi_server.filestore import ReleaseFileStore
    return ReleaseFileStore(redis, tmpdir)

@pytest.fixture
def extdb(redis, filestore, httpget):
    from devpi_server.extpypi import HTMLCache, ExtDB
    redis.flushdb()
    htmlcache = HTMLCache(redis, httpget)
    extdb = ExtDB("https://pypi.python.org/", htmlcache, filestore)
    extdb.url2response = httpget.url2response
    return extdb

@pytest.fixture
def pypiurls(xom):
    class PyPIURL:
        def __init__(self):
            self.base = xom.config.args.pypiurl
            self.simple = self.base + "simple/"
    return PyPIURL()

