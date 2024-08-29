from __future__ import annotations

from .log import threadlog
import contextlib
import threading
import time
import types


try:
    from ctypes import c_long
    from ctypes import py_object
    from ctypes import pythonapi
    PyThreadState_SetAsyncExc = pythonapi.PyThreadState_SetAsyncExc
    HAS_SETASYNCEXC = True
except ImportError:
    HAS_SETASYNCEXC = False


class Shutdown(Exception):
    """ this thread is shutting down. """


def current_thread():
    systhread = threading.current_thread()
    target = systhread._target  # type: ignore[attr-defined]
    if not isinstance(target, types.MethodType):
        return systhread
    thread = getattr(target.__self__, "thread", None)
    if not isinstance(thread, MyThread):
        return systhread
    return thread


class MyThread(threading.Thread):
    pool: ThreadPool

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

    def run(self) -> None:
        try:
            threading.Thread.run(self)
        except (KeyboardInterrupt, self.pool.Shutdown):
            pass
        except Exception as e:  # noqa: BLE001
            threadlog.exception("Exception in thread '%s'", self.name)
            self.pool._fatal_exc = e
        except BaseException as e:  # noqa: BLE001
            threadlog.exception("Fatal exception in thread '%s'", self.name)
            self.pool._fatal_exc = e
        else:
            threadlog.info("Thread '%s' ended", self.name)
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
        self._started = []

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
                try:
                    if self._a_thread_ended.wait(timeout=1):
                        if self._fatal_exc is not None:
                            raise self._fatal_exc
                        if not main_thread.is_alive():
                            break
                        self._a_thread_ended.clear()
                except KeyboardInterrupt:
                    break
        finally:
            self.shutdown()

    def start(self):
        for obj in self._objects:
            self.start_one(obj)

    def start_one(self, obj):
        assert hasattr(obj, "thread"), f"no thread registered for {obj}"
        if hasattr(obj, "thread_shutdown"):
            self._shutdown_funcs.append(obj.thread_shutdown)
        self._started.append(obj)
        obj.thread.start()

    def exit_if_shutdown(self):
        if self._shutdown.is_set():
            raise self.Shutdown()

    def shutdown(self):
        self._shutdown.set()
        for func in self._shutdown_funcs:
            func()

    def kill(self):
        self.shutdown()
        for obj in self._started:
            if obj.thread.is_alive():
                obj.thread.join(0.1)
        if not HAS_SETASYNCEXC:
            return
        for obj in self._started:
            if obj.thread.is_alive():
                with contextlib.suppress(ValueError):
                    _interrupt_thread(obj.thread.ident)


def _interrupt_thread(tid):
    '''Raises KeyboardInterrupt in the threads with id tid'''
    res = PyThreadState_SetAsyncExc(
        c_long(tid), py_object(KeyboardInterrupt))
    if res == 0:
        raise ValueError("invalid thread id")
    if res != 1:
        # "if it returns a number greater than one, you're in trouble,
        # and you should call it again with exc=NULL to revert the effect"
        PyThreadState_SetAsyncExc(c_long(tid), None)
        raise SystemError("PyThreadState_SetAsyncExc failed")
