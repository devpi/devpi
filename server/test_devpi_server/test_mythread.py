
from devpi_server import mythread
import pytest

@pytest.fixture
def pool():
    return mythread.ThreadPool()


def test_basic_interact(pool, Queue):
    queue1 = Queue()
    queue2 = Queue()
    class T:
        def thread_run(self):
            queue1.put(10)
            queue2.get()
            self.thread.exit_if_shutdown()
            queue2.get()

    t = T()
    pool.register(t)
    pool.start()
    assert queue1.get() == 10
    assert mythread.has_active_thread(t)
    pool.shutdown()
    with pytest.raises(t.thread.pool.Shutdown):
        t.thread.sleep(10)
    queue2.put(20)
    t.thread.join()
    assert not mythread.has_active_thread(t)

def test_custom_shutdown(pool, Queue):
    queue1 = Queue()
    class T:
        def thread_shutdown(self):
            queue1.put(10)

        def thread_run(self):
            queue1.get(timeout=None)
            self.thread.exit_if_shutdown()
            queue1.get()

    t = T()
    pool.register(t)
    pool.start()
    assert mythread.has_active_thread(t)
    pool.shutdown()
    t.thread.join()

def test_live(pool):
    class T:
        def thread_run(self):
            self.thread.sleep(100)

    t = T()
    pool.register(t)
    with pool.live():
        assert mythread.has_active_thread(t)
    t.thread.join()

def test_start_one(pool):
    class T:
        def thread_run(self):
            self.thread.sleep(100)

    t = T()
    pool.register(t)
    pool.start_one(t)
    assert mythread.has_active_thread(t)
    pool.shutdown()
    t.thread.join()


#def test_sleep_shutdown_wait(self, xom, monkeypatch):
#    l = []
#    monkeypatch.setattr(xom._shutdown, "wait", lambda x: l.append(x))
#    xom.sleep(10)
#    assert l == [10]
#
#def test_shutdownfunc_lifo(self, xom, caplog):
#    l = []
#    xom.addshutdownfunc("hello", lambda: l.append(1))
#    xom.addshutdownfunc("world", lambda: l.append(2))
#    xom.shutdown()
#    assert l == [2,1]
#    assert caplog.getrecords(".*hello.*")
#    assert caplog.getrecords(".*world.*")
#
#def test_spawn(self, xom, caplog):
#    l = []
#    thread = xom.spawn(lambda: l.append(1))
#    thread.join()
#    assert l == [1]
#    recs = caplog.getrecords(msgrex="execut.*")
#    assert len(recs) == 2
#    assert "execution starts" in recs[0].msg
####    assert "execution finished" in recs[1].msg
