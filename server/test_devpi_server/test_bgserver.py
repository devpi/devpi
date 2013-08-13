
import subprocess, time
import py
import pytest
from devpi_server.bgserver import BackgroundServer
from devpi_server.main import main
from requests.exceptions import ConnectionError

@pytest.fixture
def mockpopen(monkeypatch):
    # old code to mock creating of a process
    called = []
    class MockPopen:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs
            self.pid = 17
            called.append(self)
            f = kwargs["stdout"]
            f.write("Listening on port ...\n")
            f.flush()

    monkeypatch.setattr(subprocess, "Popen", MockPopen)
    return called

def test_server_commands(tmpdir, monkeypatch):
    monkeypatch.setenv("DEVPI_SERVERDIR", tmpdir)
    main(["devpi-server", "--start", "--port=3499"])
    try:
        main(["devpi-server", "--status"])
        main(["devpi-server", "--log"])
    finally:
        main(["devpi-server", "--stop"])

