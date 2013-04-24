
from devpi_server.main import XOM

import pytest
import py


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
    return client

#@pytest.fixture(autouse=True)
#def clean_redis(request):
#    if 0 and "redis" in request.fixturenames:
#        redis = request.getfuncargvalue("redis")
#        redis.flushdb()

@pytest.fixture
def xom(request):
    from devpi_server.main import preparexom
    xom = preparexom(["devpi-server"])
    request.addfinalizer(xom.kill_spawned)
    return xom

@pytest.fixture
def httpget():
    url2response = {}
    def httpget(url, allow_redirects=False):
        class response:
            def __init__(self, url):
                self.__dict__.update(url2response.get(url))
                self.url = url
                self.allow_redirects = allow_redirects
        return response(url)
    httpget.url2response = url2response
    return httpget

@pytest.fixture
def filestore(redis, tmpdir):
    from devpi_server.extpypi import ReleaseFileStore
    return ReleaseFileStore(redis, tmpdir)

@pytest.fixture
def extdb(redis, filestore, httpget):
    from devpi_server.extpypi import HTMLCache, ExtDB
    redis.flushdb()
    htmlcache = HTMLCache(redis, httpget)
    extdb = ExtDB("https://pypi.python.org/", htmlcache, filestore)
    extdb.url2response = httpget.url2response
    return extdb

