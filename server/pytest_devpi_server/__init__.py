from devpi_server.mirror import MirrorStage
from devpi_server.mirror import MirrorCustomizer
import pytest


def pytest_addoption(parser):
    parser.addoption(
        "--backend", action="store",
        help="run tests with specified dotted name backend")


@pytest.fixture
def devpiserver_makepypistage():
    def makepypistage(xom):
        from devpi_server.main import _pypi_ixconfig_default
        # we copy _pypi_ixconfig_default, otherwise the defaults will
        # be modified during config updates later on
        return MirrorStage(
            xom, username="root", index="pypi",
            ixconfig=dict(_pypi_ixconfig_default),
            customizer_cls=MirrorCustomizer)
    return makepypistage
