from devpi.main import Hub, hookimpl
from devpi.login import main
from functools import partial
from io import StringIO
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
        password = None
    return args


@pytest.fixture
def hub(args):
    out = StringIO()
    hub = Hub(args, file=out)
    hub._out = out
    return hub


@pytest.fixture
def login(args, hub, monkeypatch):
    monkeypatch.setattr("getpass.getpass", getpass)
    return partial(main, hub, args)


def test_login_asks_for_passwd(args, hub, login):
    hub.current._currentdict["login"] = "http://localhost/"
    args.password = None
    with pytest.raises(GetPassException):
        login()


def test_login(args, hub, login, mock_http_api):
    args.password = "foo"
    hub.current._currentdict["login"] = "http://localhost/"
    mock_http_api.set(hub.current.login, 200, result={
        "expiration": 36000,
        "password": "token"})
    login()
    out = hub._out.getvalue()
    assert "logged in 'user'" in out
    assert "credentials valid for 10.00 hours" in out


def test_login_without_use(hub, login):
    with pytest.raises(SystemExit):
        login()
    out = hub._out.getvalue()
    assert "not connected to a server, see 'devpi use'" in out


def test_login_plugin(args, hub, login, mock_http_api):
    passwords = ["foo"]

    class Plugin:
        @hookimpl
        def devpiclient_get_password(self, url, username):
            return passwords.pop()

    hub.pm.register(Plugin())
    args.password = None
    hub.current._currentdict["login"] = "http://localhost/"
    mock_http_api.set(hub.current.login, 200, result={
        "expiration": 36000,
        "password": "token"})
    assert len(passwords) == 1
    login()
    assert len(passwords) == 0
    out = hub._out.getvalue()
    assert "logged in 'user'" in out
    assert "credentials valid for 10.00 hours" in out


@pytest.mark.skipif("config.option.fast")
def test_login_with_index_environment(capfd, devpi, devpi_username, monkeypatch, tmpdir, url_of_liveserver):
    # remove persisted client for fresh start
    clientdir = tmpdir.join("client")
    clientdir.remove()
    monkeypatch.setenv("DEVPI_INDEX", url_of_liveserver.url)
    devpi("use")
    (out, err) = capfd.readouterr()
    assert "using server: %s/ (not logged in)" % url_of_liveserver.url in out
    devpi("login", devpi_username, "--password", "123")
    (out, err) = capfd.readouterr()
    assert 'credentials valid for' in out
    devpi("use")
    (out, err) = capfd.readouterr()
    msg = "using server: %s/ (logged in as %s)" % (
        url_of_liveserver.url,
        devpi_username)
    assert msg in out


@pytest.mark.skipif("config.option.fast")
def test_login_with_relative_index_environment(capfd, devpi, devpi_username, monkeypatch, tmpdir, url_of_liveserver):
    # remove persisted client for fresh start
    clientdir = tmpdir.join("client")
    clientdir.remove()
    devpi_index = "%s/dev" % devpi_username
    monkeypatch.setenv("DEVPI_INDEX", devpi_index)
    devpi("use", url_of_liveserver.url)
    (out, err) = capfd.readouterr()
    assert "using server: %s/ (not logged in)" % url_of_liveserver.url in out
    devpi("login", devpi_username, "--password", "123")
    (out, err) = capfd.readouterr()
    assert 'credentials valid for' in out
    devpi("use")
    (out, err) = capfd.readouterr()
    url = url_of_liveserver.joinpath(devpi_index).url
    msg = "current devpi index: %s (logged in as %s)" % (
        url,
        devpi_username)
    assert msg in out
