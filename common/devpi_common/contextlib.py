from contextlib import contextmanager  # noqa: A005
import os


try:
    from contextlib import chdir  # type: ignore[attr-defined]
except ImportError:
    @contextmanager
    def chdir(path):
        old = os.getcwd()
        try:
            os.chdir(path)
            yield old
        finally:
            os.chdir(old)
