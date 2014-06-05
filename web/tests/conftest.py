from test_devpi_server.conftest import gentmp, httpget
from test_devpi_server.conftest import makemapp, maketestapp, makexom, mapp
from test_devpi_server.conftest import dummyrequest, pypiurls, testapp
import pytest


(gentmp, httpget,
 makemapp, maketestapp, makexom, mapp,
 dummyrequest, pypiurls, testapp)  # shut up pyflakes


def pytest_addoption(parser):
    parser.addoption("--fast", help="skip functional/slow tests", default=False,
                     action="store_true")


@pytest.fixture
def xom(request, makexom):
    import devpi_web.main
    xom = makexom(plugins=[(devpi_web.main, None)])
    from devpi_server.main import set_default_indexes
    set_default_indexes(xom.model)
    return xom
