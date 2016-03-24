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

def test_version(capfd):
    main(["devpi-server", "--version"])
    out, err = capfd.readouterr()
    assert not err  # not logging output
    assert devpi_server.__version__ in out.strip()

def test_check_compatible_version_earlier(xom, monkeypatch):
    monkeypatch.setattr(xom, "get_state_version", lambda: "1.0")
    with pytest.raises(Fatal):
        check_compatible_version(xom)

def test_check_compatible_version_self(xom):
    check_compatible_version(xom)

def test_check_compatible_dev_version(xom, monkeypatch):
    monkeypatch.setattr(xom, "get_state_version", lambda: "2.3.0.dev1")
    monkeypatch.setattr("devpi_server.main.server_version", "2.3.0.dev2")
    check_compatible_version(xom)

def test_check_compatible_minor_version(xom, monkeypatch):
    monkeypatch.setattr(xom, "get_state_version", lambda: "2.2.0")
    monkeypatch.setattr("devpi_server.main.server_version", "2.3.0")
    check_compatible_version(xom)

@pytest.mark.parametrize("version", ["2.0.1", "2.1.9"])
def test_check_incompatible_minor_version_raises(xom, monkeypatch, version):
    monkeypatch.setattr(xom, "get_state_version", lambda: version)
    monkeypatch.setattr("devpi_server.main.server_version", "2.3.0")
    with pytest.raises(Fatal):
        check_compatible_version(xom)

def test_check_incompatible_version_raises(xom):
    versionfile = xom.config.serverdir.join(".serverversion")
    versionfile.write("5.0.4")
    with pytest.raises(Fatal):
        check_compatible_version(xom)

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


def test_requests_only(makexom):
    xom = makexom(opts=["--requests-only"])
    xom.create_app()
    assert not xom.thread_pool._objects

    xom = makexom(opts=["--requests-only", "--master=http://localhost:3140"])
    xom.create_app()
    assert not xom.thread_pool._objects


@wsgi_run_throws
def test_run_commands_called(tmpdir):
    from devpi_server.main import _main, get_pluginmanager
    l = []
    class Plugin:
        def devpiserver_cmdline_run(self, xom):
            l.append(xom)
            return 1
    pm = get_pluginmanager()
    pm.register(Plugin())
    result = _main(
        argv=["devpi-server", "--serverdir", str(tmpdir)],
        pluginmanager=pm)
    assert result == 1
    assert len(l) == 1
    assert isinstance(l[0], XOM)


@wsgi_run_throws
def test_main_starts_server_if_run_commands_returns_none(tmpdir):
    from devpi_server.main import _main, get_pluginmanager
    l = []
    class Plugin:
        def devpiserver_cmdline_run(self, xom):
            l.append(xom)
    pm = get_pluginmanager()
    pm.register(Plugin())
    with pytest.raises(ZeroDivisionError):
        _main(
            argv=["devpi-server", "--serverdir", str(tmpdir)],
            pluginmanager=pm)
    assert len(l) == 1
    assert isinstance(l[0], XOM)


def test_version_info(xom):
    app = xom.create_app()
    counts = {}
    for name, version in app.app.registry['devpi_version_info']:
        counts[name] = counts.get(name, 0) + 1
    assert counts['devpi-server'] == 1


def test_profiling_tween(capsys):
    class xom:
        class config:
            class args:
                profile_requests = 10
    registry = dict(xom=xom)
    handler = tween_request_profiling(lambda req: None, registry)
    for i in range(10):
        handler(None)
    out, err = capsys.readouterr()
    assert "ncalls" in out


def test_xom_singleton(xom):
    with pytest.raises(KeyError):
        xom.get_singleton("x/y", "hello")
    xom.set_singleton("x/y", "hello", {})
    d = {1:2}
    xom.set_singleton("x/y", "hello", d)
    d[2] = 3
    assert xom.get_singleton("x/y", "hello") == d
    xom.del_singletons("x/y")
    with pytest.raises(KeyError):
        assert xom.get_singleton("x/y", "hello") is None


@pytest.mark.nomocking
@pytest.mark.parametrize("url", [
    "http://someserver/path",
    "https://pypi.python.org/simple/package/",
])
@pytest.mark.parametrize("allowRedirect", [True, False])
def test_offline_mode_httpget_returns_server_error(makexom, url, allowRedirect):
    xom = makexom(["--offline-mode"], httpget=XOM.httpget)
    r = xom.httpget(url, allowRedirect)
    assert r.status_code == 503


def test_no_root_pypi_option(makexom):
    xom = makexom(["--no-root-pypi"])
    with xom.keyfs.transaction(write=False):
        stage = xom.model.getstage('root/pypi')
        assert stage is None
    xom = makexom()
    with xom.keyfs.transaction(write=False):
        stage = xom.model.getstage('root/pypi')
        assert stage is not None
        assert stage.name == 'root/pypi'
