from .log import threadlog
import contextlib
import threading
import time
import types


class Shutdown(Exception):
    """ this thread is shutting down. """


def current_thread():
    systhread = threading.current_thread()
    target = systhread._target
    if not isinstance(target, types.MethodType):
        return systhread
    thread = getattr(target.__self__, "thread", None)
    if not isinstance(thread, MyThread):
        return systhread
    return thread


class MyThread(threading.Thread):
    def sleep(self, secs):
        start = time.monotonic()
        remaining = secs
        while 1:
            to_wait = max(0.5, remaining)
            self.pool._shutdown.wait(to_wait)
            self.exit_if_shutdown()
            remaining -= (time.monotonic() - start)
            if remaining <= 0:
                break

    def exit_if_shutdown(self):
        return self.pool.exit_if_shutdown()

    def run(self):
        try:
            result = threading.Thread.run(self)
        except self.pool.Shutdown:
            pass
        except Exception as e:
            threadlog.exception(
                "Exception in thread '%s'", self.name)
            self.pool._fatal_exc = e
        except BaseException as e:
            threadlog.exception(
                "Fatal exception in thread '%s'", self.name)
            self.pool._fatal_exc = e
        else:
            threadlog.info("Thread '%s' ended", self.name)
            return result
        finally:
            self.pool._a_thread_ended.set()


def has_active_thread(obj):
    thread = getattr(obj, "thread", None)
    return thread is not None and thread.is_alive()


class ThreadPool:
    Shutdown = Shutdown

    def __init__(self):
        self._a_thread_ended = threading.Event()
        self._fatal_exc = None
        self._objects = []
        self._shutdown = threading.Event()
        self._shutdown_funcs = []

    def register(self, obj, kwargs=None, daemon=True):
        assert not isinstance(obj, threading.Thread)
        assert hasattr(obj, "thread_run")
        assert not hasattr(obj, "thread")
        thread = MyThread(
            target=obj.thread_run,
            kwargs=kwargs or {},
            name=obj.__class__.__name__,
            daemon=daemon)
        thread.pool = self
        obj.thread = thread
        self._objects.append(obj)

    @contextlib.contextmanager
    def run(self, func, *args, **kwargs):
        threadlog.debug("ThreadManager starting")
        main_thread = MyThread(
            target=func,
            args=args,
            kwargs=kwargs,
            name="MainThread",
            daemon=True)
        main_thread.pool = self
        func.thread = main_thread
        self._objects.append(func)
        try:
            self.start()
            while 1:
                if self._a_thread_ended.wait(timeout=1):
                    if self._fatal_exc is not None:
                        raise self._fatal_exc
                    if not main_thread.is_alive():
                        break
                    self._a_thread_ended.clear()
        finally:
            self.shutdown()

    def start(self):
        for obj in self._objects:
            self.start_one(obj)

    def start_one(self, obj):
        assert hasattr(obj, "thread"), f"no thread registered for {obj}"
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
