import pytest
from devpi_server import mythread
from devpi_server.config import hookimpl
from devpi_server.config import parseoptions, get_pluginmanager
from devpi_server.main import Fatal
from devpi_server.main import XOM
from devpi_server.main import check_compatible_version
from devpi_server.main import main
from devpi_server.main import tween_request_profiling
import devpi_server
import os

@pytest.fixture
def ground_wsgi_run(monkeypatch):
    monkeypatch.setattr(mythread.ThreadPool, "live", lambda *args: 0 / 0)

wsgi_run_throws = pytest.mark.usefixtures("ground_wsgi_run")


@pytest.fixture
def config(gentmp):
    serverdir = gentmp()
    pluginmanager = get_pluginmanager()
    return parseoptions(
        pluginmanager,
        ["devpi-server", "--serverdir", serverdir.strpath])


def test_pkgresources_version_matches_init():
    import pkg_resources
    ver = devpi_server.__version__
    assert pkg_resources.get_distribution("devpi_server").version == ver

def test_version(capfd):
    main(["devpi-server", "--version"])
    out, err = capfd.readouterr()
    assert not err  # not logging output
    assert devpi_server.__version__ in out.strip()

def test_check_compatible_version_earlier(config, monkeypatch):
    monkeypatch.setattr("devpi_server.main.get_state_version", lambda cfg: "1.0")
    with pytest.raises(Fatal):
        check_compatible_version(config)


@pytest.mark.parametrize("version", ["4", "4.8.1"])
def test_check_compatible_version(config, version):
    versionfile = config.serverdir.join(".serverversion")
    versionfile.write(version)
    check_compatible_version(config)


def test_check_compatible_dev_version(config, monkeypatch):
    monkeypatch.setattr("devpi_server.main.get_state_version", lambda cfg: "2.3.0.dev1")
    monkeypatch.setattr("devpi_server.main.DATABASE_VERSION", "2")
    check_compatible_version(config)


def test_check_compatible_minor_version(config, monkeypatch):
    monkeypatch.setattr("devpi_server.main.get_state_version", lambda cfg: "2.2.0")
    monkeypatch.setattr("devpi_server.main.DATABASE_VERSION", "2")
    check_compatible_version(config)


@pytest.mark.parametrize("version", ["2.0.1", "2.1.9"])
def test_check_incompatible_minor_version_raises(config, monkeypatch, version):
    monkeypatch.setattr("devpi_server.main.get_state_version", lambda cfg: version)
    with pytest.raises(Fatal):
        check_compatible_version(config)


def test_check_incompatible_version_raises(config):
    versionfile = config.serverdir.join(".serverversion")
    versionfile.write("5.0.4")
    with pytest.raises(Fatal):
        check_compatible_version(config)


def test_pyramid_configure_called(makexom):
    l = []
    class Plugin:
        @hookimpl
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
        @hookimpl
        def devpiserver_cmdline_run(self, xom):
            l.append(xom)
            return 1
    pm = get_pluginmanager()
    pm.register(Plugin())
    result = _main(
        argv=["devpi-server", "--init", "--serverdir", str(tmpdir)],
        pluginmanager=pm)
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
        @hookimpl
        def devpiserver_cmdline_run(self, xom):
            l.append(xom)
    pm = get_pluginmanager()
    pm.register(Plugin())
    _main(
        argv=["devpi-server", "--init", "--serverdir", str(tmpdir)],
        pluginmanager=pm)
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
    "https://pypi.org/simple/package/",
])
@pytest.mark.parametrize("allowRedirect", [True, False])
def test_offline_mode_httpget_returns_server_error(makexom, url, allowRedirect):
    xom = makexom(["--offline-mode"], httpget=XOM.httpget)
    r = xom.httpget(url, allowRedirect)
    assert r.status_code == 503


@pytest.mark.nomocking
def test_replica_max_retries_option(makexom, monkeypatch):
    from devpi_server.main import new_requests_session as orig_new_requests_session
    def new_requests_session(*args, **kwargs):
        _max_retries = None
        if 'max_retries' in kwargs:
            _max_retries = kwargs['max_retries']
        elif len(args)>=2:
            _max_retries = args[1]
        assert _max_retries == 2
        return orig_new_requests_session()

    xom = makexom(["--replica-max-retries=2"])
    monkeypatch.setenv("HTTP_PROXY", "http://this")
    monkeypatch.setenv("HTTPS_PROXY", "http://that")
    monkeypatch.setattr("devpi_server.main.new_requests_session", new_requests_session)

    r = xom.httpget("http://example.com", allow_redirects=False,
                              timeout=1.2)
    assert r.status_code == -1


@pytest.mark.nomocking
@pytest.mark.parametrize("input_set", [
    {'timeout': 5, 'arg': [], 'kwarg': None},
    {'timeout': 42, 'arg': ["--request-timeout=42"], 'kwarg': None},
    {'timeout': 123, 'arg': [], 'kwarg': 123}
])
def test_request_args_timeout_handover(makexom, input_set):
    def mock_http_get(*args, **kwargs):
        assert kwargs["timeout"] == input_set['timeout']
    xom = makexom(input_set['arg'])
    xom._httpsession.get = mock_http_get

    xom.httpget("http://whatever", allow_redirects=False, timeout=input_set['kwarg'])


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


def test_no_init_empty_directory(call_devpi_in_dir, tmpdir):
    assert not len(os.listdir(tmpdir.strpath))
    result = call_devpi_in_dir(tmpdir, [])
    assert not len(os.listdir(tmpdir.strpath))
    result.stderr.fnmatch_lines("*contains no devpi-server data*")


def test_init_empty_directory(call_devpi_in_dir, monkeypatch, tmpdir):
    monkeypatch.setattr("devpi_server.config.Config.init_nodeinfo", lambda x: 0/0)
    assert not len(os.listdir(tmpdir.strpath))
    with pytest.raises(ZeroDivisionError):
        call_devpi_in_dir(tmpdir, ["devpi-server", "--init"])


def test_no_init_no_server_directory(call_devpi_in_dir, tmpdir):
    tmpdir.ensure("foo")
    assert os.listdir(tmpdir.strpath) == ["foo"]
    result = call_devpi_in_dir(tmpdir, [])
    assert os.listdir(tmpdir.strpath) == ["foo"]
    result.stderr.fnmatch_lines("*contains no devpi-server data*")


def test_init_no_server_directory(call_devpi_in_dir, monkeypatch, tmpdir):
    monkeypatch.setattr("devpi_server.config.Config.init_nodeinfo", lambda x: 0/0)
    tmpdir.ensure("foo")
    assert os.listdir(tmpdir.strpath) == ["foo"]
    with pytest.raises(ZeroDivisionError):
        call_devpi_in_dir(tmpdir, ["devpi-server", "--init"])


def test_init_server_directory(call_devpi_in_dir, tmpdir):
    tmpdir.ensure(".nodeinfo")
    assert os.listdir(tmpdir.strpath) == [".nodeinfo"]
    result = call_devpi_in_dir(tmpdir, ["devpi-server", "--init"])
    assert os.listdir(tmpdir.strpath) == [".nodeinfo"]
    result.stderr.fnmatch_lines("*already contains devpi-server data*")


def test_serve_threads(monkeypatch, tmpdir):
    def check_threads(app, host, port, threads, max_request_body_size):
        assert threads == 100
    monkeypatch.setattr("waitress.serve", check_threads)
    from devpi_server.main import main
    main(["devpi-server", "--threads", "100"])


def test_serve_max_body(monkeypatch, tmpdir):
    def check_max_body(app, host, port, threads, max_request_body_size):
        assert max_request_body_size == 42
    monkeypatch.setattr("waitress.serve", check_max_body)
    from devpi_server.main import main
    main(["devpi-server", "--max-request-body-size", "42"])


def test_root_passwd_option(makexom):
    # by default the password is empty
    xom = makexom()
    with xom.keyfs.transaction(write=False):
        user = xom.model.get_user('root')
        assert user.validate("")
        assert not user.validate("foobar")
    # the password can be set from the command line
    xom = makexom(["--root-passwd", "foobar"])
    with xom.keyfs.transaction(write=False):
        user = xom.model.get_user('root')
        assert not user.validate("")
        assert user.validate("foobar")


def test_root_passwd_hash_option(makexom):
    # by default the password is empty
    xom = makexom()
    with xom.keyfs.transaction(write=False):
        user = xom.model.get_user('root')
        assert user.validate("")
        assert not user.validate("foobar")
    # the password hash can be directly set from the command line
    xom = makexom(["--root-passwd-hash", "$argon2i$v=19$m=102400,t=2,p=8$j9G6V8o5B0Co9f4fQ6gVIg$WzcG2C5Bv0LwtzPWeBcz0g"])
    with xom.keyfs.transaction(write=False):
        user = xom.model.get_user('root')
        assert not user.validate("")
        assert user.validate("foobar")
