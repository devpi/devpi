
import urllib
import pytest
import py
from devpi import config
from devpi import log
from devpi.main import Hub
from devpi.config import main, Config
from devpi.config import parse_keyvalue_spec

class TestUnit:
    def test_write_and_read(self, tmpdir):
        path=tmpdir.join("config")
        config = Config(path)
        assert not config.simpleindex
        config.reconfigure(dict(
                pypisubmit="/post", pushrelease="/push",
                simpleindex="/index",
                login="/login",
                resultlog="/"))
        assert config.simpleindex
        newconfig = Config(path)
        assert newconfig.pypisubmit == config.pypisubmit
        assert newconfig.simpleindex == config.simpleindex
        assert newconfig.resultlog == config.resultlog
        assert newconfig.venvdir == config.venvdir
        assert newconfig.login == config.login

    def test_normalize_url(self, tmpdir):
        config = Config(tmpdir.join("config"))
        config.reconfigure(dict(simpleindex="http://my.serv/index1"))
        url = config._normalize_url("index2")
        assert url == "http://my.serv/index2/"

    def test_main(self, tmpdir, monkeypatch, cmd_devpi):
        monkeypatch.chdir(tmpdir)
        api = dict(
                   status=200,
                   resource = dict(
                        pypisubmit="/post", pushrelease="/push",
                        simpleindex="/index/",
                        resultlog="/resultlog/",
                   ))
        def http_api(*args, **kwargs):
            return api

        from devpi import main
        monkeypatch.setattr(main.Hub, "http_api", http_api)
        hub = cmd_devpi("config", "http://world/this")
        newapi = hub.config
        assert newapi.pypisubmit == "http://world/post"
        assert newapi.pushrelease == "http://world/push"
        assert newapi.simpleindex == "http://world/index/"
        assert newapi.resultlog == "http://world/resultlog/"
        assert not newapi.venvdir

        hub = cmd_devpi("config", "--delete")
        assert not hub.config.exists()

    def test_main_venvsetting(self, cmd_devpi, tmpdir, monkeypatch):
        venvdir = tmpdir
        monkeypatch.chdir(tmpdir)
        hub = cmd_devpi("config", "venv=%s" % venvdir)
        config = Config(hub.config.path)
        assert config.venvdir == str(venvdir)

        # test via env
        monkeypatch.setenv("WORKON_HOME", venvdir.dirpath())
        hub = cmd_devpi("config", "venv=%s" % venvdir.basename)
        assert hub.config.venvdir == venvdir



@pytest.mark.parametrize("input expected".split(), [
    (["hello=123", "world=42"], dict(hello="123", world="42")),
    (["hello=123=1"], dict(hello="123=1"))
    ])
def test_parse_keyvalue_spec(input, expected):
    result = parse_keyvalue_spec(input, "hello world".split())
    assert result == expected

def test_parse_keyvalue_spec_unknown_key():
    pytest.raises(KeyError, lambda: parse_keyvalue_spec(["hello=3"], ["some"]))


