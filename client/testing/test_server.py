
import subprocess, time
import py
import pytest
from devpi.server import AutoServer, default_rooturl, main
from requests.exceptions import ConnectionError

@pytest.fixture
def mockpopen(monkeypatch):
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

def test_server_start_stop(makehub):
    hub = makehub(["server"])
    server = AutoServer(hub)
    server.start(None, "http://localhost:3145")
    server.stop()

def test_log(loghub):
    autoserver = AutoServer(loghub)
    autoserver.info.logpath


