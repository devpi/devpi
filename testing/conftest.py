
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
    client.flushdb()  # empty the current DB
    return client
