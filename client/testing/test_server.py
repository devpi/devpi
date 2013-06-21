
import subprocess, time
import py
import pytest
from devpi.server import handle_autoserver, AutoServer, default_rooturl, main
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

@pytest.mark.parametrize("raising", [True, False])
@pytest.mark.parametrize("rooturl", ["/", default_rooturl])
@pytest.mark.parametrize("logfile", [None, "line1\nline2\nline3\n"])
def test_handle_autoserver(loghub, tmpdir, monkeypatch, raising, rooturl,
                           mockpopen, logfile):
    l = []
    class current:
        simpleindex = None
        @classmethod
        def configure_fromurl(cls, hub, url):
            assert url == default_rooturl + "/root/dev/"
            l.append(1)
    current.rooturl = rooturl

    def head(url):
        assert url == default_rooturl
        if raising:
            raise ConnectionError()
        else:
            return py.io.BytesIO()

    g = []
    def get(url):
        g.append(1)
        return

    monkeypatch.setattr(loghub.http, "head", head)
    monkeypatch.setattr(loghub.http, "get", get)
    monkeypatch.delenv("DEVPI_NO_AUTOSERVER")
    if raising:
        handle_autoserver(loghub, current)
        assert l == [1]
        assert len(g) == 1
    else:
        handle_autoserver(loghub, current)
        assert l == [1]
        autoserver = AutoServer(loghub)
        if logfile:
            autoserver.info.logpath.ensure()
            autoserver.info.logpath.write(logfile)
        autoserver.log()

def test_handle_autoserver_does_nothing_with_non_default(loghub):
    class current:
        rooturl = "http://localhost:3142/"
    loghub.http = None
    handle_autoserver(loghub, current)

def test_log(loghub):
    autoserver = AutoServer(loghub)
    autoserver.info.logpath


