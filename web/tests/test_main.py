

def test_importable():
    import devpi_web
    assert devpi_web


def test_pkgresources_version_matches_init():
    import devpi_web
    import pkg_resources
    ver = devpi_web.__version__
    assert pkg_resources.get_distribution("devpi_web").version == ver


def test_devpi_mirror_initialnames(monkeypatch, pypistage, mock):
    import devpi_web.main
    from devpi_web.main import devpiserver_mirror_initialnames
    iter_projects = mock.MagicMock()
    iter_projects.return_value = iter([])
    monkeypatch.setattr(devpi_web.main, "iter_projects", iter_projects)
    with pypistage.keyfs.transaction():
        devpiserver_mirror_initialnames(pypistage, pypistage.list_projects_perstage())
    assert iter_projects.called


def test_devpi_stage_created(monkeypatch, pypistage, mock):
    from devpi_web.main import devpiserver_stage_created
    list_projects_perstage = mock.MagicMock()
    list_projects_perstage.return_value = []
    monkeypatch.setattr(pypistage, "list_projects_perstage", list_projects_perstage)
    with pypistage.keyfs.transaction():
        devpiserver_stage_created(pypistage)
    assert list_projects_perstage.called


def test_index_projects_arg(monkeypatch, tmpdir):
    from devpi_web.main import get_indexer
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

    monkeypatch.setattr(devpi_server.main, "XOM", MyXOM)

    result = devpi_server.main.main(
        ["devpi-server", "--serverdir", str(tmpdir), "--init"])
    assert not result
    result = devpi_server.main.main(
        ["devpi-server", "--serverdir", str(tmpdir), "--recreate-search-index"])
    assert result == 0
    assert tmpdir.join('.indices').check()
    (xom1, xom2) = xom_container
    ix = get_indexer(xom2.config)
    result = ix.query_projects('foo')
    assert result['info']['found'] == 1
    assert result['items'][0]['data'] == {
        u'index': u'pypi',
        u'name': u'foo',
        u'path': u'/root/pypi/foo',
        u'type': u'project',
        u'user': u'root'}
