import pytest


def test_importable():
    import devpi_web
    assert devpi_web


def test_index_created_on_first_run(monkeypatch, tmpdir):
    from mock import MagicMock
    import devpi_server.main
    import devpi_web.main
    iter_projects = MagicMock()
    iter_projects.return_value = iter([])
    monkeypatch.setattr(devpi_server.extpypi.PyPIMirror, "init_pypi_mirror",
                        lambda self, proxy: None)
    monkeypatch.setattr(devpi_web.main, "iter_projects", iter_projects)
    monkeypatch.setattr(devpi_server.main, "wsgi_run", lambda *x: 0 / 0)
    with pytest.raises(ZeroDivisionError):
        devpi_server.main.main(["devpi-server", "--serverdir", str(tmpdir)])
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
        ["devpi-server", "--serverdir", str(tmpdir), "--index-projects"])
    assert tmpdir.join('.indices').check()
    (xom,) = xom_container
    ix = get_indexer(xom.config)
    result = ix.query_projects('foo')
    assert result['info']['found'] == 1
    assert result['items'][0]['data'] == {
        u'index': u'pypi',
        u'name': u'foo',
        u'path': u'/root/pypi/foo',
        u'text_type': u'project',
        u'user': u'root'}
