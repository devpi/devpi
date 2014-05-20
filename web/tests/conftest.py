from test_devpi_server.conftest import gentmp, httpget
from test_devpi_server.conftest import makemapp, maketestapp, makexom, mapp
from test_devpi_server.conftest import pypiurls, testapp
import pytest


(gentmp, httpget,
 makemapp, maketestapp, makexom, mapp,
 pypiurls, testapp)  # shut up pyflakes


@pytest.fixture
def xom(request, makexom):
    import devpi_web.main
    xom = makexom(plugins=[(devpi_web.main, None)])
    from devpi_server.main import set_default_indexes
    set_default_indexes(xom.model)
    return xom
