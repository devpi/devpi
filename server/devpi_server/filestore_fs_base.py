from __future__ import annotations

from .fileutil import get_write_file_ensure_dir
from .interfaces import IIOFile
from .keyfs_types import FilePathInfo
from .log import threadlog
from .markers import Deleted
from .markers import deleted
from contextlib import suppress
from hashlib import sha256
from typing import TYPE_CHECKING
from zope.interface import Interface
from zope.interface import alsoProvides
from zope.interface import implementer
import os
import shutil
import sys
import threading


if TYPE_CHECKING:
    from .interfaces import ContentOrFile
    from collections.abc import Callable
    from collections.abc import Iterable
    from pathlib import Path
    from types import TracebackType
    from typing import IO
    from typing_extensions import Self


class ITempStorageFile(Interface):
    """Marker interface."""


class DirtyFile:
    def __init__(self, path: str) -> None:
        self.path = path
        # use hash of path, pid and thread id to prevent conflicts
        key = f"{path}{os.getpid()}{threading.current_thread().ident}"
        digest = sha256(key.encode("utf-8")).hexdigest()
        if sys.platform == "win32":
            # on windows we have to shorten the digest, otherwise we reach
            # the 260 chars file path limit too quickly
            digest = digest[:8]
        self.tmppath = f"{path}-{digest}-tmp"

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} {self.path}>"

    @classmethod
    def from_content(cls, path: str, content_or_file: ContentOrFile) -> DirtyFile:
        self = DirtyFile(path)
        if hasattr(content_or_file, "devpi_srcpath"):
            dirname = os.path.dirname(self.tmppath)
            if not os.path.exists(dirname):
                # ignore file exists errors
                # one reason for that error is a race condition where
                # another thread tries to create the same folder
                with suppress(FileExistsError):
                    os.makedirs(dirname)
            os.link(content_or_file.devpi_srcpath, self.tmppath)
        else:
            with get_write_file_ensure_dir(self.tmppath) as f:
                if isinstance(content_or_file, bytes):
                    f.write(content_or_file)
                else:
                    assert content_or_file.seekable()
                    content_or_file.seek(0)
                    shutil.copyfileobj(content_or_file, f)
        return self


@implementer(IIOFile)
class FSIOFileBase:
    _dirty_files: dict[str, DirtyFile | Deleted]

    def __init__(self, base_path: Path, settings: dict) -> None:
        self.settings = settings
        self.basedir = base_path
        self._dirty_files = {}

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        cls: type[BaseException] | None,
        val: BaseException | None,
        tb: TracebackType | None,
    ) -> bool | None:
        if cls is not None:
            self.rollback()
            return False
        self._commit("wrote files: %s")
        return True

    def _commit(self, msg: str) -> None:
        raise NotImplementedError

    def _make_path(self, path: FilePathInfo) -> str:
        raise NotImplementedError

    def delete(self, path: FilePathInfo) -> None:
        assert isinstance(path, FilePathInfo)
        _path = self._make_path(path)
        old = self._dirty_files.get(_path)
        if isinstance(old, DirtyFile):
            os.remove(old.tmppath)
        self._dirty_files[_path] = deleted

    def exists(self, path: FilePathInfo) -> bool:
        assert isinstance(path, FilePathInfo)
        _path = self._make_path(path)
        if _path in self._dirty_files:
            dirty_file = self._dirty_files[_path]
            if isinstance(dirty_file, Deleted):
                return False
            _path = dirty_file.tmppath
        return os.path.exists(_path)

    def get_content(self, path: FilePathInfo) -> bytes:
        assert isinstance(path, FilePathInfo)
        _path = self._make_path(path)
        if _path in self._dirty_files:
            dirty_file = self._dirty_files[_path]
            if isinstance(dirty_file, Deleted):
                raise OSError
            _path = dirty_file.tmppath
        with open(_path, "rb") as f:
            data = f.read()
            if len(data) > 1048576:
                threadlog.warn(
                    "Read %.1f megabytes into memory in get_content for %s",
                    len(data) / 1048576,
                    _path,
                )
            return data

    def is_dirty(self) -> bool:
        return bool(self._dirty_files)

    def is_path_dirty(self, path: FilePathInfo) -> bool:
        return self._make_path(path) in self._dirty_files

    def new_open(self, path: FilePathInfo) -> IO[bytes]:
        assert isinstance(path, FilePathInfo)
        assert not self.exists(path)
        _path = self._make_path(path)
        assert not _path.endswith("-tmp")
        f = get_write_file_ensure_dir(DirtyFile(_path).tmppath)
        alsoProvides(f, ITempStorageFile)
        return f

    def open_read(self, path: FilePathInfo) -> IO[bytes]:
        assert isinstance(path, FilePathInfo)
        _path = self._make_path(path)
        if _path in self._dirty_files:
            dirty_file = self._dirty_files[_path]
            if isinstance(dirty_file, Deleted):
                raise OSError
            _path = dirty_file.tmppath
        return open(_path, "rb")

    def os_path(self, path: FilePathInfo) -> str:
        assert isinstance(path, FilePathInfo)
        return str(self.basedir / path.relpath)

    def set_content(self, path: FilePathInfo, content_or_file: ContentOrFile) -> None:
        assert isinstance(path, FilePathInfo)
        _path = self._make_path(path)
        assert not _path.endswith("-tmp")
        if ITempStorageFile.providedBy(content_or_file):
            self._dirty_files[_path] = DirtyFile(_path)
        else:
            self._dirty_files[_path] = DirtyFile.from_content(_path, content_or_file)

    def size(self, path: FilePathInfo) -> int | None:
        assert isinstance(path, FilePathInfo)
        _path = self._make_path(path)
        if _path in self._dirty_files:
            dirty_file = self._dirty_files[_path]
            if isinstance(dirty_file, Deleted):
                return None
            _path = dirty_file.tmppath
        with suppress(OSError):
            return os.path.getsize(_path)
        return None

    def commit(self) -> None:
        self._commit("wrote files without increasing serial: %s")

    def iter_rel_renames(self) -> Iterable[str]:
        raise NotImplementedError

    def get_rel_renames(self) -> list[str]:
        # produce a list of strings which are
        # - paths relative to basedir
        # - if they have "-tmp" at the end it means they should be renamed
        #   to the path without the "-tmp" suffix
        # - if they don't have "-tmp" they should be removed
        return list(self.iter_rel_renames())

    def perform_crash_recovery(
        self,
        iter_rel_renames: Callable[[], Iterable[str]],
        iter_file_path_infos: Callable[[Iterable[str]], Iterable[FilePathInfo]],
    ) -> None:
        raise NotImplementedError

    def rollback(self) -> None:
        for dirty_file in self._dirty_files.values():
            if isinstance(dirty_file, DirtyFile):
                os.remove(dirty_file.tmppath)
        self._dirty_files.clear()
