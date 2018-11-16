import pytest
import pysober

def pytest_addoption(parser):
    group = parser.getgroup('sober', 'sober specific options')
    group.addoption('--project-version',
                    default = pysober.__version__,
                    dest='vstring',
                    help='expected project version - default %s' % pysober.__version__)

@pytest.fixture()
def pysober_expected_version(request):
    return request.config.getvalue('vstring')
