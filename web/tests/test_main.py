import pytest


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


def test_index_projects_arg(monkeypatch, tmpdir):
    from devpi_web.null_index import Index as NullIndex
    import devpi_server.main
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

    result = devpi_server.main.main([
        "devpi-server", "--serverdir", str(tmpdir),
        "--indexer-backend", "null",
        "--init"])
    assert calls == []
    assert not result
    result = devpi_server.main.main([
        "devpi-server", "--serverdir", str(tmpdir),
        "--indexer-backend", "null",
        "--recreate-search-index", "--offline"])
    assert result == 0
    assert calls == ['delete_index', 'update_projects']
    (xom1, xom2) = xom_container
