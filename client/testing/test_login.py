from devpi.main import Hub, hookimpl
from devpi.login import main
from functools import partial
import py
import pytest


class GetPassException(Exception):
    pass


def getpass(msg):
    raise GetPassException()


@pytest.fixture
def args(tmpdir):
    class args:
        clientdir = tmpdir.join("client")
        username = "user"
    return args


@pytest.fixture
def hub(args):
    out = py.io.TextIO()
    hub = Hub(args, file=out)
    hub._out = out
    hub.current._currentdict["login"] = "http://localhost/"
    return hub


@pytest.fixture
def login(args, hub, monkeypatch):
    monkeypatch.setattr("getpass.getpass", getpass)
    return partial(main, hub, args)


def test_login_asks_for_passwd(args, login):
    args.password = None
    with pytest.raises(GetPassException):
        login()


def test_login(args, hub, login, mock_http_api):
    args.password = "foo"
    mock_http_api.set(hub.current.login, 200, result={
        "expiration": 36000,
        "password": "token"})
    login()
    out = hub._out.getvalue()
    assert "logged in 'user'" in out
    assert "credentials valid for 10.00 hours" in out


def test_login_plugin(args, hub, login, mock_http_api):
    passwords = ["foo"]

    class Plugin:
        @hookimpl
        def devpiclient_get_password(self, url, username):
            return passwords.pop()

    hub.pm.register(Plugin())
    args.password = None
    mock_http_api.set(hub.current.login, 200, result={
        "expiration": 36000,
        "password": "token"})
    assert len(passwords) == 1
    login()
    assert len(passwords) == 0
    out = hub._out.getvalue()
    assert "logged in 'user'" in out
    assert "credentials valid for 10.00 hours" in out
