from contextlib import contextmanager
try:
    from contextlib import chdir
except ImportError:
    @contextmanager
    def chdir(path):
        old = os.getcwd()
        try:
            os.chdir(path)
            yield old
        finally:
            os.chdir(old)
import os
