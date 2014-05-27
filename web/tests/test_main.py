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
    monkeypatch.setattr(devpi_server.extpypi.PyPIStage, "init_pypi_mirror",
                        lambda self, proxy: None)
    monkeypatch.setattr(devpi_web.main, "iter_projects", iter_projects)
    monkeypatch.setattr(devpi_server.main, "wsgi_run", lambda xom: 0 / 0)
    with pytest.raises(ZeroDivisionError):
        devpi_server.main.main(["devpi-server", "--serverdir", str(tmpdir)])
    assert iter_projects.called


@pytest.mark.skipif("config.option.fast")
def test_index_projects_arg(monkeypatch, tmpdir):
    import devpi_server.main
    monkeypatch.setattr(devpi_server.extpypi.PyPIStage, "init_pypi_mirror",
                        lambda self, proxy: None)
    monkeypatch.setattr(devpi_server.extpypi.PyPIStage, "name2serials", {},
                        raising=False)
    # if the webserver is started, we fail
    monkeypatch.setattr(devpi_server.main, "wsgi_run", lambda xom: 0 / 0)
    devpi_server.main.main(
        ["devpi-server", "--serverdir", str(tmpdir), "--index-projects"])
    assert tmpdir.join('.indices').check()
