import pytest
from devpi_server.main import *
import devpi_server


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
    monkeypatch.setattr(devpi_server.main, "wsgi_run", lambda *args: None)
    def record(basedir):
        assert tmpdir.join("root", "pypi") == basedir
        0/0
    monkeypatch.setattr(devpi_server.extpypi, "invalidate_on_version_change",
                        lambda xom: 0/0)
    with pytest.raises(ZeroDivisionError):
        main(["devpi-server", "--serverdir", str(tmpdir)])

def test_startup_fails_on_initial_setup_nonetwork(tmpdir, monkeypatch):
    monkeypatch.setattr(devpi_server.main, "wsgi_run", lambda **kw: 0/0)
    monkeypatch.setattr(devpi_server.main, "PYPIURL_XMLRPC",
                        "http://qwqwlekjqwlekqwe.notexists")
    ret = main(["devpi-server", "--serverdir", str(tmpdir)])
    assert ret


def test_pyramid_configure_called(makexom):
    l = []
    class Plugin:
        def devpiserver_pyramid_configure(self, config, pyramid_config):
            l.append((config, pyramid_config))
    xom = makexom(plugins=[(Plugin(),None)])
    xom.create_app(immediatetasks=-1)
    assert len(l) == 1
    config, pyramid_config = l[0]
    assert config == xom.config
    
