
import urllib
import pytest
import py
from devpi import use
from devpi import log
from devpi.main import Hub, parse_args
from devpi.use import main, Current
from devpi.use import parse_keyvalue_spec

def test_ask_confirm(makehub, monkeypatch):
    import devpi.main
    hub = makehub(["remove", "something"])
    monkeypatch.setattr(devpi.main, "raw_input", lambda msg: "yes",
                        raising=False)
    assert hub.ask_confirm("hello")
    monkeypatch.setattr(devpi.main, "raw_input", lambda msg: "no")
    assert not hub.ask_confirm("hello")
    l = ["yes", "qwoeiu"]
    monkeypatch.setattr(devpi.main, "raw_input", lambda msg: l.pop())
    assert hub.ask_confirm("hello")

def test_ask_confirm_delete_args_yes(makehub):
    hub = makehub(["remove", "-y", "whatever"])
    assert hub.ask_confirm("hello")

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

    def test_use_with_no_rooturl(self, capfd, cmd_devpi, monkeypatch):
        from devpi import main
        monkeypatch.setattr(main.Hub, "http_api", None)
        with pytest.raises(SystemExit):
            hub = cmd_devpi("use", "some/index", code=200)
        out, err = capfd.readouterr()
        assert "invalid" in out

    def test_use_with_nonexistent_domain(self, capfd, cmd_devpi, monkeypatch):
        from devpi import main
        from requests.sessions import Session
        from requests.exceptions import ConnectionError
        def raise_connectionerror(*args, **kwargs):
            raise ConnectionError("qwe")
        monkeypatch.setattr(Session, "request", raise_connectionerror)
        with pytest.raises(SystemExit):
            hub = cmd_devpi("use", "http://qlwkejqlwke", code=200)
        out, err = capfd.readouterr()
        assert "could not connect" in out

    def test_main(self, tmpdir, monkeypatch, cmd_devpi):
        monkeypatch.chdir(tmpdir)
        api = dict(
                   status=200,
                   result = dict(
                        pypisubmit="/post",
                        simpleindex="/index/",
                        resultlog="/resultlog/",
                        index="root/some",
                        bases="root/dev",
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
        assert newapi.bases == "http://world/root/dev"
        assert not newapi.venvdir

        # some url helpers
        assert hub.get_index_url(slash=False) == "http://world/root/some"
        assert hub.get_index_url() == "http://world/root/some/"
        assert hub.get_project_url("pytest") == \
                                    "http://world/root/some/pytest/"

        #hub = cmd_devpi("use", "--delete")
        #assert not hub.current.exists()

    def test_main_venvsetting(self, out_devpi, cmd_devpi, tmpdir, monkeypatch):
        from devpi.use import vbin
        venvdir = tmpdir
        venvdir.ensure(vbin, dir=1)
        monkeypatch.chdir(tmpdir)
        hub = cmd_devpi("use", "--no-auto", "--venv=%s" % venvdir)
        current = Current(hub.current.path)
        assert current.venvdir == str(venvdir)
        hub = cmd_devpi("use", "--no-auto", "--venv=%s" % venvdir)
        res = out_devpi("use", "--no-auto")
        res.stdout.fnmatch_lines("*venv*%s" % venvdir)

        # test via env
        monkeypatch.setenv("WORKON_HOME", venvdir.dirpath())
        hub = cmd_devpi("use", "--no-auto", "--venv=%s" % venvdir.basename)
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
