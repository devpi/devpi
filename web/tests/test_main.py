from devpi_common.metadata import parse_version
from devpi_server import __version__ as _devpi_server_version
from devpi_web.compat import read_transaction
import pytest
import textwrap


devpi_server_version = parse_version(_devpi_server_version)
pytestmark = [pytest.mark.notransaction]


def test_importable():
    import devpi_web
    assert devpi_web


def test_devpi_mirror_initialnames(caplog, pypistage):
    import logging
    caplog.set_level(logging.NOTSET)
    from devpi_web.main import devpiserver_mirror_initialnames
    pypistage.mock_simple_projects(["pytest"])
    pypistage.mock_simple(
        "pytest", pypiserial=10,
        pkgver="pytest-1.0.zip#egg=pytest-dev1")
    with read_transaction(pypistage.keyfs):
        devpiserver_mirror_initialnames(pypistage, pypistage.list_projects_perstage())
    logs = [x for x in caplog.messages if 'after exception' in x]
    assert len(logs) == 0
    logs = [x for x in caplog.messages if 'finished mirror indexing operation' in x]
    assert len(logs) == 1


@pytest.mark.skipif(
    devpi_server_version < parse_version("6.6.0dev"),
    reason="Needs un-normalized project names from list_projects_perstage on mirrors")
def test_devpi_mirror_initialnames_original_name(caplog, pypistage):
    import logging
    caplog.set_level(logging.NOTSET)
    from devpi_common.validation import normalize_name
    from devpi_web.main import devpiserver_mirror_initialnames
    from devpi_web.main import get_indexer
    projects = set(["Django", "pytest", "ploy_ansible"])
    pypistage.mock_simple_projects(projects)
    pypistage.mock_simple(
        "Django", pypiserial=10,
        pkgver="django-1.0.zip")
    indexer = get_indexer(pypistage.xom)
    pypistage.xom.thread_pool.start_one(indexer.indexer_thread)
    with read_transaction(pypistage.keyfs):
        devpiserver_mirror_initialnames(pypistage, pypistage.list_projects_perstage())
    indexer.indexer_thread.wait()
    for project in projects:
        (item1,) = indexer.query_projects(project)['items']
        (item2,) = indexer.query_projects(normalize_name(project))['items']
        data1 = item1['data']
        data2 = item2['data']
        assert data1 == data2
        assert data1['name'] == project


def test_devpi_stage_created(monkeypatch, pypistage, mock):
    from devpi_web.main import devpiserver_stage_created
    list_projects_perstage = mock.MagicMock()
    list_projects_perstage.return_value = []
    monkeypatch.setattr(
        pypistage.__class__, "list_projects_perstage", list_projects_perstage)
    with read_transaction(pypistage.keyfs):
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

        def httpget(self, url, allow_redirects=True, extra_headers=None):  # noqa: ARG002
            class Response:
                def __init__(self):
                    self.status_code = 200
                    self.text = """<a href='foo'>foo</a>"""
                    self.url = url
            return Response()

        def create_app(self):
            # if the webserver is started, we fail
            0 / 0  # noqa: B018

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
            def __init__(self, config, settings):  # noqa: ARG002
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
            def __init__(self, config, settings):  # noqa: ARG002
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
