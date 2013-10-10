import sys
import types
import pytest
from devpi_server.main import *
import devpi_server

def test_get_bottle_server(monkeypatch):
    assert get_bottle_server("wsgiref") == "wsgiref"
    assert get_bottle_server("eventlet") == "eventlet"
    monkeypatch.setitem(sys.modules, "eventlet", None)
    assert get_bottle_server("auto") == "wsgiref"

def test_get_bottle_server_eventlet_if_exists(monkeypatch):
    mod = types.ModuleType("eventlet")
    monkeypatch.setitem(sys.modules, "eventlet", mod)
    assert get_bottle_server("auto") == "eventlet"


def test_check_compatible_version_earlier(xom, monkeypatch):
    monkeypatch.setattr(xom, "get_state_version", lambda: "1.0")
    with pytest.raises(Fatal):
        check_compatible_version(xom)

def test_check_compatible_version_self(xom):
    check_compatible_version(xom)

def test_check_incompatible_version_raises(xom):
    versionfile = xom.config.serverdir.join(".serverversion")
    versionfile.write("5.0.4")
    with pytest.raises(Fatal):
        check_compatible_version(xom)

def test_invalidate_is_called(monkeypatch, tmpdir):
    monkeypatch.setattr(devpi_server.main, "bottle_run", lambda *args: None)
    def record(basedir):
        assert tmpdir.join("root", "pypi") == basedir
        0/0
    monkeypatch.setattr(devpi_server.extpypi, "invalidate_on_version_change",
                        lambda xom: 0/0)
    with pytest.raises(ZeroDivisionError):
        main(["devpi-server", "--serverdir", str(tmpdir)])

def test_startup_fails_on_initial_setup_nonetwork(tmpdir, monkeypatch):
    import bottle
    monkeypatch.setattr(bottle, "run", lambda **kw: 0/0)
    monkeypatch.setattr(devpi_server.main, "PYPIURL_XMLRPC",
                        "http://qwqwlekjqwlekqwe.notexists")
    ret = main(["devpi-server", "--serverdir", str(tmpdir)])
    assert ret
