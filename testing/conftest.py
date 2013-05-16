
import re
import logging
import mimetypes
import pytest
import py
from devpi_server.main import XOM, add_redis_keys
from devpi_server.config import configure_redis_start


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

@pytest.fixture(scope="session")
def redis(request, xprocess):
    """ return a session-wide StrictRedis connection which is connected
    to an externally started redis server instance
    (through the xprocess plugin)"""
    redis = pytest.importorskip("redis")
    port = 6500
    try:
        prepare_redis = configure_redis_start(port=port)
    except configure_redis_start.Error:
        pytest.skip("command not found: redis-server")
    pid, redislogfile = xprocess.ensure("redis", prepare_redis)
    def kill():
        try:
            py.process.kill(pid)
        except OSError:
            import inspect
            warn_lineno = inspect.currentframe().f_lineno - 3
            import warnings
            msg = "Failed to kill redis instance (pid %d)" % pid
            warnings.warn_explicit(msg, RuntimeWarning, __file__, warn_lineno)
    if pid:
        request.addfinalizer(kill)
    client = redis.StrictRedis(port=port)
    client.port = port
    add_redis_keys(client)
    return client


@pytest.fixture(autouse=True)
def clean_redis(request):
    if "redis" in request.fixturenames:
    #if request.cls and getattr(request.cls, "cleanredis", False):
        redis = request.getfuncargvalue("redis")
        redis.flushdb()

@pytest.fixture
def xom_notmocked(request, redis):
    from devpi_server.main import parseoptions, XOM
    config = parseoptions(["devpi-server", "--redisport", str(redis.port)])
    xom = XOM(config)
    request.addfinalizer(xom.shutdown)
    return xom

@pytest.fixture
def xom(request, redis, filestore, httpget):
    from devpi_server.main import parseoptions, XOM
    from devpi_server.extpypi import ExtDB
    config = parseoptions(["devpi-server", "--redisport", str(redis.port)])
    xom = XOM(config)
    xom.redis = redis
    xom.releasefilestore = filestore
    xom.redis.flushdb()
    xom.httpget = httpget
    xom.extdb = ExtDB(xom=xom)
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
    from devpi_server.db import DB, set_default_indexes
    db = DB(xom)
    set_default_indexes(db)
    return db

