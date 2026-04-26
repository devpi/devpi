import pytest


pytest_plugins = ["pytest_devpi_server", "test_devpi_server.plugin"]


@pytest.fixture
def xom(makexom):
    import devpi_debugging.main
    import devpi_web.main

    return makexom(
        opts=("--debug-keyfs",),
        plugins=[(devpi_debugging.main, None), (devpi_web.main, None)],
    )
