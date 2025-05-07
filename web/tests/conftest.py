from textwrap import dedent
import pytest


pytest_plugins = ["pytest_devpi_server", "test_devpi_server.plugin"]


def pytest_addoption(parser):
    parser.addoption("--fast", help="skip functional/slow tests", default=False,
                     action="store_true")


@pytest.fixture
def xom(request, makexom):
    import devpi_web.main
    xom = makexom(plugins=[(devpi_web.main, None)])
    return xom


@pytest.fixture
def theme_path(request, tmp_path):
    marker = request.node.get_closest_marker("theme_files")
    files = {} if marker is None else marker.args[0]
    path = tmp_path / "theme"
    path.mkdir(parents=True, exist_ok=True)
    path.joinpath("static").mkdir(parents=True, exist_ok=True)
    path.joinpath("templates").mkdir(parents=True, exist_ok=True)
    for filepath, content in files.items():
        path.joinpath(*filepath).write_text(dedent(content))
    return path


@pytest.fixture(params=[None, "tox38"])
def tox_result_data(request):
    from test_devpi_server.example import tox_result_data
    import copy
    tox_result_data = copy.deepcopy(tox_result_data)
    if request.param == "tox38":
        retcode = int(tox_result_data['testenvs']['py27']['test'][0]['retcode'])
        tox_result_data['testenvs']['py27']['test'][0]['retcode'] = retcode
    return tox_result_data


@pytest.fixture(params=[True, False])
def keep_docs_packed(monkeypatch, request):
    value = request.param

    def func(config):
        return value

    monkeypatch.setattr("devpi_web.doczip.keep_docs_packed", func)
    return value


@pytest.fixture
def bs_text():
    def bs_text(resultset):
        return ' '.join(''.join(x.text for x in resultset).split())

    return bs_text
