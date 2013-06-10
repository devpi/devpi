
import subprocess, time
import py
import pytest
from devpi.server import ensure_autoserver, AutoServer, default_rooturl, main
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
def test_ensure_autoserver(loghub, tmpdir, monkeypatch, raising, rooturl,
                           mockpopen, logfile):
    l = []
    class current:
        simpleindex = None
        @classmethod
        def configure_fromurl(cls, hub, url):
            assert url == default_rooturl + "root/dev/"
            l.append(1)
    current.rooturl = rooturl

    def head(url):
        assert url == default_rooturl
        if raising:
            raise ConnectionError()
        else:
            return py.io.BytesIO()

    monkeypatch.setattr(loghub.http, "head", head)
    if raising:
        ensure_autoserver(loghub, current)
        assert l == [1]
    else:
        ensure_autoserver(loghub, current)
        assert not l
        autoserver = AutoServer(loghub)
        if logfile:
            autoserver.info.logpath.ensure()
            autoserver.info.logpath.write(logfile)
        autoserver.log()

def test_ensure_autoserver_does_nothing_with_non_default(loghub):
    class current:
        rooturl = "http://localhost:3142/"
    loghub.http = None
    ensure_autoserver(loghub, current)

def test_log(loghub):
    autoserver = AutoServer(loghub)
    autoserver.info.logpath


