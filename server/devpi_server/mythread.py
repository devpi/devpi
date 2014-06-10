import threading

class XOMThread(threading.Thread):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("name", self.__class__)
        threading.Thread.__init__(self, *args, **kwargs)
        self.setDaemon(True)

    def is_shutting_down(self):
        return hasattr(self, "_shutdown")

class ThreadPool:
    def __init__(self):
        self._threads = []

    def register(self, thread):
        self._threads.append(thread)

    def start_registered_threads(self):
        for thread in self._threads:
            thread.start()

    def shutdown(self):
        for thread in self._threads:
            thread._shutdown = True

