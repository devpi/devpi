import pytest

class TestXOM:
    def test_sleep_shutdown(self, xom):
        xom.shutdown()
        pytest.raises(xom.Exiting, lambda: xom.sleep(100.0))

    def test_sleep_shutdown_wait(self, xom, monkeypatch):
        l = []
        monkeypatch.setattr(xom._shutdown, "wait", lambda x: l.append(x))
        xom.sleep(10)
        assert l == [10]

    def test_shutdownfunc_lifo(self, xom, caplog):
        l = []
        xom.addshutdownfunc("hello", lambda: l.append(1))
        xom.addshutdownfunc("world", lambda: l.append(2))
        xom.shutdown()
        assert l == [2,1]
        assert caplog.getrecords(".*hello.*")
        assert caplog.getrecords(".*world.*")

    def test_spawn(self, xom, caplog):
        l = []
        thread = xom.spawn(lambda: l.append(1))
        thread.join()
        assert l == [1]
        recs = caplog.getrecords(msgrex="execut.*")
        assert len(recs) == 2
        assert "execution starts" in recs[0].msg
        assert "execution finished" in recs[1].msg
