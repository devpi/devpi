
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

    def test_auth_multisite(self, tmpdir):
        current = Current(tmpdir.join("current"))
        login1 = "http://site.com/+login"
        login2 = "http://site2.com/+login"
        current.set_auth("hello", "pass1", login1)
        current.set_auth("hello", "pass2", login2)
        assert current.get_auth(login1) == ("hello", "pass1")
        assert current.get_auth(login2) == ("hello", "pass2")
        current.del_auth(login1)
        assert not current.get_auth(login1)
        assert current.get_auth(login2) == ("hello", "pass2")
        current.del_auth(login2)
        assert not current.get_auth(login2)

    def test_invalid_url(self, loghub, tmpdir):
        current = Current(tmpdir.join("current"))
        with pytest.raises(SystemExit):
            current.configure_fromurl(loghub, "http://heise.de:/qwe")

    def test_use_with_no_rooturl(self, capfd, cmd_devpi, monkeypatch):
        from devpi import main
        monkeypatch.setattr(main.Hub, "http_api", None)
        hub = cmd_devpi("use", "some/index", code=None)
        out, err = capfd.readouterr()
        assert "invalid" in out

    def test_use_with_nonexistent_domain(self, capfd, cmd_devpi, monkeypatch):
        from devpi import main
        from requests.sessions import Session
        from requests.exceptions import ConnectionError
        def raise_connectionerror(*args, **kwargs):
            raise ConnectionError("qwe")
        monkeypatch.setattr(Session, "request", raise_connectionerror)
        hub = cmd_devpi("use", "http://qlwkejqlwke", code=-1)
        out, err = capfd.readouterr()
        assert "could not connect" in out

    def test_change_index(self, cmd_devpi, mock_http_api):
        mock_http_api.set("http://world.com/+api", 200,
                    result=dict(
                        index="/index",
                        login="/+login/",
                   ))
        mock_http_api.set("http://world2.com/+api", 200,
                    result=dict(
                        login="/+login/",
                   ))

        hub = cmd_devpi("use", "http://world.com")
        assert hub.current.index == "http://world.com/index"
        assert hub.current.rooturl == "http://world.com/"

        hub = cmd_devpi("use", "http://world2.com")
        assert not hub.current.index
        assert hub.current.rooturl == "http://world2.com/"

    def test_main(self, cmd_devpi, mock_http_api):
        mock_http_api.set("http://world/this/+api", 200,
                    result=dict(
                        pypisubmit="/post",
                        simpleindex="/index/",
                        resultlog="/resultlog/",
                        index="root/some",
                        bases="root/dev",
                        login="/+login/",
                   ))

        hub = cmd_devpi("use", "http://world/this")
        newapi = hub.current
        assert newapi.pypisubmit == "http://world/post"
        assert newapi.simpleindex == "http://world/index/"
        assert newapi.resultlog == "http://world/resultlog/"
        assert not newapi.venvdir

        # some url helpers
        current = hub.current
        assert current.get_index_url(slash=False) == "http://world/root/some"
        assert current.get_index_url() == "http://world/root/some/"
        assert current.get_project_url("pytest") == \
                                    "http://world/root/some/pytest/"

        #hub = cmd_devpi("use", "--delete")
        #assert not hub.current.exists()

    def test_main_list(self, out_devpi, cmd_devpi, mock_http_api):
        mock_http_api.set("http://world/+api", 200,
                    result=dict(
                        pypisubmit="",
                        simpleindex="",
                        resultlog="/resultlog/",
                        index="",
                        bases="",
                        login="/+login/",
                   ))

        hub = cmd_devpi("use", "http://world/")
        mock_http_api.set("http://world/", 200, result=dict(
            user1=dict(indexes={"dev": {"bases": ["x"]}})
        ))
        out = out_devpi("use", "-l")
        out.stdout.fnmatch_lines("""
            user1/dev*x*
        """)

    def test_main_venvsetting(self, out_devpi, cmd_devpi, tmpdir, monkeypatch):
        from devpi.use import vbin
        venvdir = tmpdir
        venvdir.ensure(vbin, dir=1)
        monkeypatch.chdir(tmpdir)
        hub = cmd_devpi("use", "--venv=%s" % venvdir)
        current = Current(hub.current.path)
        assert current.venvdir == str(venvdir)
        hub = cmd_devpi("use", "--venv=%s" % venvdir)
        res = out_devpi("use")
        res.stdout.fnmatch_lines("*venv*%s" % venvdir)

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
