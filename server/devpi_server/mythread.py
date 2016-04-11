import contextlib
import threading
from traceback import print_exc


class Shutdown(Exception):
    """ this thread is shutting down. """


class MyThread(threading.Thread):
    def sleep(self, secs):
        self.pool._shutdown.wait(secs)
        self.exit_if_shutdown()

    def exit_if_shutdown(self):
        return self.pool.exit_if_shutdown()

    def run(self):
        try:
            return threading.Thread.run(self)
        except self.pool.Shutdown:
            pass
        except:
            print_exc()


def has_active_thread(obj):
    thread = getattr(obj, "thread", None)
    return thread is not None and thread.is_alive()


class ThreadPool:
    Shutdown = Shutdown

    def __init__(self):
        self._objects = []
        self._shutdown = threading.Event()
        self._shutdown_funcs = []

    def register(self, obj, kwargs=None, daemon=True):
        assert not isinstance(obj, threading.Thread)
        assert hasattr(obj, "thread_run")
        assert not hasattr(obj, "thread")
        thread = MyThread(target=obj.thread_run, kwargs=kwargs or {},
                          name=obj.__class__.__name__)
        thread.setDaemon(daemon)
        thread.pool = self
        obj.thread = thread
        self._objects.append(obj)

    @contextlib.contextmanager
    def live(self):
        self.start()
        try:
            yield
        finally:
            self.shutdown()

    def start(self):
        for obj in self._objects:
            self.start_one(obj)

    def start_one(self, obj):
        assert hasattr(obj, "thread"), "no thread registered for %s" %(obj,)
        if hasattr(obj, "thread_shutdown"):
            self._shutdown_funcs.append(obj.thread_shutdown)
        obj.thread.start()

    def exit_if_shutdown(self):
        if self._shutdown.is_set():
            raise self.Shutdown()

    def shutdown(self):
        self._shutdown.set()
        for func in self._shutdown_funcs:
            func()
