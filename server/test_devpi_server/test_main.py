import pytest
from devpi_server.main import *
import devpi_server

@pytest.fixture
def ground_wsgi_run(monkeypatch):
    monkeypatch.setattr(mythread.ThreadPool, "live", lambda *args: 0 / 0)

wsgi_run_throws = pytest.mark.usefixtures("ground_wsgi_run")


def test_pkgresources_version_matches_init():
    import pkg_resources
    ver = devpi_server.__version__
    assert pkg_resources.get_distribution("devpi_server").version == ver

def test_check_compatible_version_earlier(xom, monkeypatch):
    monkeypatch.setattr(xom, "get_state_version", lambda: "1.0")
    with pytest.raises(Fatal):
        check_compatible_version(xom)

def test_check_compatible_version_self(xom):
    check_compatible_version(xom)

def test_check_compatible_dev_version(xom, monkeypatch):
    monkeypatch.setattr(xom, "get_state_version", lambda: "2.1.0.dev1")
    monkeypatch.setattr("devpi_server.main.server_version", "2.1.0.dev2")
    check_compatible_version(xom)

def test_check_incompatible_version_raises(xom):
    versionfile = xom.config.serverdir.join(".serverversion")
    versionfile.write("5.0.4")
    with pytest.raises(Fatal):
        check_compatible_version(xom)

@wsgi_run_throws
def test_startup_fails_on_initial_setup_nonetwork(tmpdir, monkeypatch):
    monkeypatch.setattr(devpi_server.main, "PYPIURL_XMLRPC",
                        "http://localhost:1")
    ret = main(["devpi-server", "--serverdir", str(tmpdir)])
    assert ret


def test_pyramid_configure_called(makexom):
    l = []
    class Plugin:
        def devpiserver_pyramid_configure(self, config, pyramid_config):
            l.append((config, pyramid_config))
    xom = makexom(plugins=[Plugin()])
    xom.create_app()
    assert len(l) == 1
    config, pyramid_config = l[0]
    assert config == xom.config


@wsgi_run_throws
def test_run_commands_called(monkeypatch, tmpdir):
    from devpi_server.main import _main, get_pluginmanager
    l = []
    class Plugin:
        def devpiserver_cmdline_run(self, xom):
            l.append(xom)
            return 1
    monkeypatch.setattr(devpi_server.extpypi.PyPIMirror, "init_pypi_mirror",
                        lambda self, proxy: None)
    pm = get_pluginmanager()
    pm.register(Plugin())
    result = _main(
        argv=["devpi-server", "--serverdir", str(tmpdir)],
        pluginmanager=pm)
    assert result == 1
    assert len(l) == 1
    assert isinstance(l[0], XOM)


@wsgi_run_throws
def test_main_starts_server_if_run_commands_returns_none(monkeypatch, tmpdir):
    from devpi_server.main import _main, get_pluginmanager
    l = []
    class Plugin:
        def devpiserver_cmdline_run(self, xom):
            l.append(xom)
    monkeypatch.setattr(devpi_server.extpypi.PyPIMirror, "init_pypi_mirror",
                        lambda self, proxy: None)
    pm = get_pluginmanager()
    pm.register(Plugin())
    with pytest.raises(ZeroDivisionError):
        _main(
            argv=["devpi-server", "--serverdir", str(tmpdir)],
            pluginmanager=pm)
    assert len(l) == 1
    assert isinstance(l[0], XOM)
