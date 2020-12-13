
from devpi_server import mythread
import pytest


@pytest.fixture
def pool():
    pool = mythread.ThreadPool()
    yield pool
    pool.shutdown()


def test_basic_interact(pool, TimeoutQueue):
    queue1 = TimeoutQueue()
    queue2 = TimeoutQueue()

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


def test_custom_shutdown(pool, TimeoutQueue):
    queue1 = TimeoutQueue()

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
