
import urllib
import pytest
import py
from devpi import use
from devpi import log
from devpi.main import Hub
from devpi.use import main, Current
from devpi.use import parse_keyvalue_spec

class TestUnit:
    def test_write_and_read(self, tmpdir):
        path=tmpdir.join("current")
        current = Current(path)
        assert not current.simpleindex
        current.reconfigure(dict(
                pypisubmit="/post",
                simpleindex="/index",
                login="/login",
                resultlog="/"))
        assert current.simpleindex
        newcurrent = Current(path)
        assert newcurrent.pypisubmit == current.pypisubmit
        assert newcurrent.simpleindex == current.simpleindex
        assert newcurrent.resultlog == current.resultlog
        assert newcurrent.venvdir == current.venvdir
        assert newcurrent.login == current.login

    def test_normalize_url(self, tmpdir):
        current = Current(tmpdir.join("current"))
        current.reconfigure(dict(simpleindex="http://my.serv/index1"))
        url = current._normalize_url("index2")
        assert url == "http://my.serv/index2/"

    def test_main(self, tmpdir, monkeypatch, cmd_devpi):
        monkeypatch.chdir(tmpdir)
        api = dict(
                   status=200,
                   result = dict(
                        pypisubmit="/post",
                        simpleindex="/index/",
                        resultlog="/resultlog/",
                        login="/+login/",
                   ))
        def http_api(*args, **kwargs):
            return api

        from devpi import main
        monkeypatch.setattr(main.Hub, "http_api", http_api)
        hub = cmd_devpi("use", "http://world/this")
        newapi = hub.current
        assert newapi.pypisubmit == "http://world/post"
        assert newapi.simpleindex == "http://world/index/"
        assert newapi.resultlog == "http://world/resultlog/"
        assert not newapi.venvdir

        #hub = cmd_devpi("use", "--delete")
        #assert not hub.current.exists()

    def test_main_venvsetting(self, cmd_devpi, tmpdir, monkeypatch):
        venvdir = tmpdir
        monkeypatch.chdir(tmpdir)
        hub = cmd_devpi("use", "--venv=%s" % venvdir)
        current = Current(hub.current.path)
        assert current.venvdir == str(venvdir)

        # test via env
        monkeypatch.setenv("WORKON_HOME", venvdir.dirpath())
        hub = cmd_devpi("use", "--venv=%s" % venvdir.basename)
        assert hub.current.venvdir == venvdir



@pytest.mark.parametrize("input expected".split(), [
    (["hello=123", "world=42"], dict(hello="123", world="42")),
    (["hello=123=1"], dict(hello="123=1"))
    ])
def test_parse_keyvalue_spec(input, expected):
    result = parse_keyvalue_spec(input, "hello world".split())
    assert result == expected

def test_parse_keyvalue_spec_unknown_key():
    pytest.raises(KeyError, lambda: parse_keyvalue_spec(["hello=3"], ["some"]))


