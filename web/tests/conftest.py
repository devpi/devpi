from test_devpi_server.conftest import gentmp, httpget, makemapp  # noqa
from test_devpi_server.conftest import maketestapp, makexom, mapp  # noqa
from test_devpi_server.conftest import pypiurls, testapp, pypistage  # noqa
from test_devpi_server.conftest import dummyrequest, pypiurls, testapp  # noqa
from test_devpi_server.conftest import simpypi, simpypiserver  # noqa
from test_devpi_server.conftest import storage_info  # noqa
from test_devpi_server.conftest import mock, pyramidconfig  # noqa
from test_devpi_server.conftest import speed_up_sqlite  # noqa
from test_devpi_server.conftest import speed_up_sqlite_fs  # noqa
try:
    from test_devpi_server.conftest import lower_argon2_parameters  # noqa
except ImportError:
    pass
import pytest


(makexom,)  # shut up pyflakes


def pytest_addoption(parser):
    parser.addoption("--fast", help="skip functional/slow tests", default=False,
                     action="store_true")


@pytest.fixture
def xom(request, makexom):
    import devpi_web.main
    xom = makexom(plugins=[(devpi_web.main, None)])
    return xom


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
