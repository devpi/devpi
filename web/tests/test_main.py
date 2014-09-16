

def test_importable():
    import devpi_web
    assert devpi_web


def test_pkgresources_version_matches_init():
    import devpi_web
    import pkg_resources
    ver = devpi_web.__version__
    assert pkg_resources.get_distribution("devpi_web").version == ver


def test_devpi_pypi_initial(monkeypatch, pypistage, mock):
    import devpi_web.main
    from devpi_web.main import devpiserver_pypi_initial
    iter_projects = mock.MagicMock()
    iter_projects.return_value = iter([])
    monkeypatch.setattr(devpi_web.main, "iter_projects", iter_projects)
    devpiserver_pypi_initial(pypistage, pypistage.pypimirror.name2serials)
    assert iter_projects.called


def test_index_projects_arg(monkeypatch, tmpdir):
    from devpi_web.main import get_indexer
    import devpi_server.main
    XOM = devpi_server.main.XOM
    xom_container = []

    def MyXOM(config):
        xom = XOM(config)
        xom_container.append(xom)
        return xom
    # provide dummy data to avoid fetching mirror data from pypi
    n2s = {u'foo': 1}
    n2n = {u'foo': u'foo'}
    monkeypatch.setattr(
        devpi_server.extpypi.PyPIMirror, "init_pypi_mirror", lambda s, p: None)
    monkeypatch.setattr(
        devpi_server.extpypi.PyPIMirror, "name2serials", n2s, raising=False)
    monkeypatch.setattr(
        devpi_server.extpypi.PyPIMirror, "normname2name", n2n, raising=False)
    monkeypatch.setattr(devpi_server.main, "XOM", MyXOM)
    # if the webserver is started, we fail
    monkeypatch.setattr(devpi_server.main, "wsgi_run", lambda *x: 0 / 0)
    devpi_server.main.main(
        ["devpi-server", "--serverdir", str(tmpdir), "--recreate-search-index"])
    assert tmpdir.join('.indices').check()
    (xom,) = xom_container
    ix = get_indexer(xom.config)
    result = ix.query_projects('foo')
    assert result['info']['found'] == 1
    assert result['items'][0]['data'] == {
        u'index': u'pypi',
        u'name': u'foo',
        u'path': u'/root/pypi/foo',
        u'type': u'project',
        u'user': u'root'}
