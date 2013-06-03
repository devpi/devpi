# coding=utf8
import os

import py
import pytest

try:
    import urllib2
except ImportError:
    import urllib.request as urllib2
pytest_plugins = "pytester",

from devpi.test.inject import pytest_devpi as plugin
from devpi.test import test

def test_version():
    assert plugin.__version__

@pytest.fixture
def file0():
    f = py.io.TextIO()
    f.write(". test_pass.py::test_pass1\n")
    f.write("F test_fail.py::test_fail1\n longrepr1\n")
    f.write("s test_skip.py::test_skip1\n skiprepr1\n")
    f.seek(0)
    return f

def test_env_match(gen):
    kw = dict(packageurl="http://some.where/pkg-1.0.zip",
              packagemd5=gen.md5(),
              posturl="http://post.com")
    env = {}
    test.setenv_devpi(env, **kw)
    newkw = plugin.popenv_devpi(env)
    assert newkw == kw
    assert not env

def test_setenv_unicode(gen):
    x = py.builtin._totext("http://some.where/pkg-1.0.zip")
    kw = dict(packageurl=x,
              packagemd5=x,
              posturl=x,)
    env = {}
    test.setenv_devpi(env, **kw)
    newkw = plugin.popenv_devpi(env)
    for val in newkw.values():
        assert isinstance(val, str)
    assert newkw == kw
    assert not env



def test_gen_dump_read(file0, tmpdir, gen):
    packageurl = "http://somewhere.com/package.tgz"
    packagemd5 = gen.md5()
    res = plugin.ReprResultLog(packageurl, packagemd5,
                               **plugin.getplatforminfo())
    res.parse_resultfile(file0)
    assert res.packageurl == packageurl
    assert res.packagemd5 == packagemd5
    assert res.pyversion == py.std.sys.version.replace("\n", "--")
    assert res.platformstring == py.std.platform.platform()
    assert res.platform == py.std.sys.platform
    data = res.dump()
    res2 = plugin.ReprResultLog.new_fromfile(py.io.TextIO(data))
    assert res2 == res

class TestPost:
    def test_postresultlog(self, file0, monkeypatch, gen):
        l = []
        def post(request):
            l.append(request)
            class response:
                code = 201
                headers = {"location": "somelocation"}
            return response
        monkeypatch.setattr(urllib2, "urlopen", post)
        loc = plugin.postresultlog(
                    posturl="http://post.url",
                    packageurl="http://package.url",
                    packagemd5=gen.md5(),
                    resultfile=file0)
        assert loc == "somelocation"
        assert len(l) == 1
        req = l[0]
        assert req.headers["Content-type"] == "text/plain"
        assert req.get_full_url() == "http://post.url"
        data_received = py.builtin._totext(req.data, "utf8")
        res = plugin.ReprResultLog.new_fromfile(py.io.TextIO(data_received))
        assert len(res.entries) == 3

    def test_postresults_error(self, file0, monkeypatch, tmpdir, gen):
        import json, platform
        def post(*args, **kwargs):
            stream = py.io.TextIO(py.builtin._totext("hello"))
            raise urllib2.HTTPError("url", 502, "bad", {}, stream)
        monkeypatch.setattr(urllib2, "urlopen", post)
        loc = plugin.postresultlog(
                    posturl="http://post.url",
                    packageurl="http://package.url",
                    packagemd5=gen.md5(),
                    resultfile=file0)
        assert loc.status_code == 502
        assert loc.data == "hello"

def test_plugin_init_withresultlog(monkeypatch, gen, tmpdir):
    monkeypatch.setenv("DEVPY_PACKAGEURL", "http://xyz.net")
    monkeypatch.setenv("DEVPY_PACKAGEMD5", gen.md5())
    monkeypatch.setenv("DEVPY_POSTURL", "http://post.url")
    class config:
        class option:
            resultlog = tmpdir.ensure("x")
        class pluginmanager:
            @classmethod
            def getplugin(self, name):
                assert name == "terminalreporter"
                class Term:
                    _tw = py.io.TerminalWriter()
                return Term()

    l = []
    monkeypatch.setenv("PYTEST_PLUGINS", "hello")
    plugin.pytest_configure(config)
    assert "PYTEST_PLUGINS" not in os.environ
    monkeypatch.setattr(plugin, "postresultlog", lambda *args, **kwargs:
        l.append(kwargs))
    plugin.pytest_unconfigure(config)
    assert len(l) == 1
    assert l[0]["packageurl"] == "http://xyz.net"

def test_plugin_init_no_resultlog(monkeypatch, tmpdir, gen):
    monkeypatch.setenv("DEVPY_PACKAGEURL", "http://xyz.net")
    monkeypatch.setenv("DEVPY_PACKAGEMD5", gen.md5())
    monkeypatch.setenv("DEVPY_POSTURL", "http://post.url")
    class config:
        class option:
            resultlog = ""
        class pluginmanager:
            @classmethod
            def getplugin(self, name):
                assert name == "terminalreporter"
                class Term:
                    _tw = py.io.TerminalWriter()
                return Term()

    monkeypatch.setenv("PYTEST_PLUGINS", "hello")
    plugin.pytest_configure(config)
    l = []
    monkeypatch.setattr(plugin, "postresultlog", lambda *args, **kwargs:
            l.append(kwargs))
    with open(config.option.resultlog, "w") as f:
        f.write("")
    plugin.pytest_unconfigure(config)
    assert len(l) == 1
    assert l[0]["packageurl"] == "http://xyz.net"
