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
                        "http://localhost:1")
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


def test_run_commands_called(monkeypatch, tmpdir):
    from devpi_server.main import _main
    l = []
    class Plugin:
        def devpiserver_run_commands(self, xom):
            l.append(xom)
            return 1
    monkeypatch.setattr(devpi_server.extpypi.PyPIMirror, "init_pypi_mirror",
                        lambda self, proxy: None)
    # catch if _main doesn't return after run_commands
    monkeypatch.setattr(devpi_server.main, "wsgi_run", lambda xom: 0 / 0)
    result = _main(
        argv=["devpi-server", "--serverdir", str(tmpdir)],
        hook=PluginManager([(Plugin(), None)]))
    assert result == 1
    assert len(l) == 1
    assert isinstance(l[0], XOM)


def test_main_starts_server_if_run_commands_returns_none(monkeypatch, tmpdir):
    from devpi_server.main import _main
    l = []
    class Plugin:
        def devpiserver_run_commands(self, xom):
            l.append(xom)
    monkeypatch.setattr(devpi_server.extpypi.PyPIMirror, "init_pypi_mirror",
                        lambda self, proxy: None)
    # catch if _main doesn't return after run_commands
    monkeypatch.setattr(devpi_server.main, "wsgi_run", lambda xom: 0 / 0)
    with pytest.raises(ZeroDivisionError):
        _main(
            argv=["devpi-server", "--serverdir", str(tmpdir)],
            hook=PluginManager([(Plugin(), None)]))
    assert len(l) == 1
    assert isinstance(l[0], XOM)
