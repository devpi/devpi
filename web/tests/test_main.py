from devpi_server import __version__ as devpi_server_version
from pkg_resources import parse_version
import pytest
import textwrap


devpi_server_version = parse_version(devpi_server_version)


def test_importable():
    import devpi_web
    assert devpi_web


def test_pkgresources_version_matches_init():
    import devpi_web
    import pkg_resources
    ver = devpi_web.__version__
    assert pkg_resources.get_distribution("devpi_web").version == ver


@pytest.mark.nomockprojectsremote
def test_devpi_mirror_initialnames(caplog, pypistage):
    import logging
    caplog.set_level(logging.NOTSET)
    from devpi_web.main import devpiserver_mirror_initialnames
    pypistage.mock_simple_projects(["pytest"])
    pypistage.mock_simple(
        "pytest", pypiserial=10,
        pkgver="pytest-1.0.zip#egg=pytest-dev1")
    with pypistage.keyfs.transaction():
        devpiserver_mirror_initialnames(pypistage, pypistage.list_projects_perstage())
    logs = [x for x in caplog.messages if 'after exception' in x]
    assert len(logs) == 0
    logs = [x for x in caplog.messages if 'finished mirror indexing operation' in x]
    assert len(logs) == 1


def test_devpi_stage_created(monkeypatch, pypistage, mock):
    from devpi_web.main import devpiserver_stage_created
    list_projects_perstage = mock.MagicMock()
    list_projects_perstage.return_value = []
    monkeypatch.setattr(pypistage, "list_projects_perstage", list_projects_perstage)
    with pypistage.keyfs.transaction():
        devpiserver_stage_created(pypistage)
    assert list_projects_perstage.called


def test_clear_index_cmd(monkeypatch, tmpdir):
    from devpi_web.null_index import Index as NullIndex
    import devpi_server.init
    import devpi_server.main
    import devpi_web.clear_index
    XOM = devpi_server.main.XOM
    xom_container = []

    class MyXOM(XOM):
        def __init__(self, config):
            xom_container.append(self)
            XOM.__init__(self, config)

        def httpget(self, url, allow_redirects=True, extra_headers=None):
            class Response:
                def __init__(self):
                    self.status_code = 200
                    self.text = """<a href='foo'>foo</a>"""
                    self.url = url
            return Response()

        def create_app(self):
            # if the webserver is started, we fail
            0 / 0

    calls = []

    monkeypatch.setattr(devpi_server.main, "XOM", MyXOM)
    monkeypatch.setattr(
        NullIndex, "delete_index",
        lambda s: calls.append("delete_index"))
    monkeypatch.setattr(
        NullIndex, "update_projects",
        lambda s, x, clear=True: calls.append("update_projects"))

    result = devpi_server.init.init(argv=[
        "devpi-init", "--serverdir", str(tmpdir)])
    assert calls == []
    assert not result
    devpi_web.clear_index.clear_index(argv=[
        "devpi-clear-search-index", "--serverdir", str(tmpdir),
        "--indexer-backend", "null"])
    assert calls == ['delete_index']
    (xom1, xom2) = xom_container


def make_config(args):
    from devpi_server.config import parseoptions, get_pluginmanager
    return parseoptions(get_pluginmanager(), args)


class TestConfig:
    @pytest.fixture(params=(True, False))
    def make_yaml_config(self, request, tmpdir):
        def make_yaml_config(content):
            yaml = tmpdir.join('devpi.yaml')
            if request.param is True:
                content = "---\n" + content
            yaml.write(content)
            return yaml.strpath

        return make_yaml_config

    def test_indexer_backend_options(self):
        from devpi_web import main
        from pluggy import HookimplMarker
        hookimpl = HookimplMarker("devpiweb")

        class Index(object):
            def __init__(self, config, settings):
                self.settings = settings

        class Plugin:
            @hookimpl
            def devpiweb_indexer_backend(self):
                return dict(
                    indexer=Index,
                    name="foo",
                    description="Foo backend")
        options = ("--indexer-backend", "foo:bar=ham")
        config = make_config(("devpi-server",) + options)
        assert config.args.indexer_backend == "foo:bar=ham"
        plugin = Plugin()
        main.get_pluginmanager(config).register(plugin)
        indexer = main.get_indexer_from_config(config)
        assert isinstance(indexer, Index)
        assert indexer.settings == {"bar": "ham"}

    @pytest.mark.skipif(devpi_server_version < parse_version("4.7dev"), reason="Needs config file support")
    def test_indexer_backend_yaml_options(self, make_yaml_config):
        from devpi_web import main
        from pluggy import HookimplMarker
        hookimpl = HookimplMarker("devpiweb")

        class Index(object):
            def __init__(self, config, settings):
                self.settings = settings

        class Plugin:
            @hookimpl
            def devpiweb_indexer_backend(self):
                return dict(
                    indexer=Index,
                    name="foo",
                    description="Foo backend")
        yaml_path = make_yaml_config(textwrap.dedent("""\
            devpi-server:
              indexer-backend:
                name: foo
                bar: ham"""))
        options = ("-c", yaml_path)
        config = make_config(("devpi-server",) + options)
        assert isinstance(config.args.indexer_backend, dict)
        plugin = Plugin()
        main.get_pluginmanager(config).register(plugin)
        indexer = main.get_indexer_from_config(config)
        assert isinstance(indexer, Index)
        assert indexer.settings == {"bar": "ham"}
