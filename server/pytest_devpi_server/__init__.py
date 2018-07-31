from devpi_server.extpypi import PyPIStage
import pytest


def pytest_addoption(parser):
    parser.addoption(
        "--slow", action="store_true", default=False,
        help="run slow tests involving remote services (pypi.org)")
    parser.addoption(
        "--backend", action="store",
        help="run tests with specified dotted name backend")


@pytest.fixture
def devpiserver_makepypistage():
    def makepypistage(xom):
        from devpi_server.main import _pypi_ixconfig_default
        return PyPIStage(xom, username="root", index="pypi",
                         ixconfig=_pypi_ixconfig_default)
    return makepypistage
