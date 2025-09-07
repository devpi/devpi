from __future__ import annotations

from .filestore_fs_base import FSIOFileBase
from .filestore_fs_base import IDirtyFile
from .filestore_fs_base import IDirtyFileFactory
from .filestore_fs_base import IFile
from .filestore_fs_base import IFileFactory
from .filestore_fs_base import tmpsuffix_for_path
from .fileutil import rename
from .interfaces import IIOFileFactory
from .log import threadlog
from attrs import field
from attrs import frozen
from contextlib import closing
from contextlib import suppress
from hashlib import sha256
from pathlib import Path
from typing import TYPE_CHECKING
from typing import cast
from zope.interface import implementer
from zope.interface import provider
import os
import shutil
import sys
import threading


if TYPE_CHECKING:
    from .interfaces import ContentOrFile
    from .keyfs import KeyFSConn
    from .keyfs import KeyFSConnWithClosing
    from .keyfs_types import FilePathInfo
    from .keyfs_types import RelPath
    from collections.abc import Iterable
    from typing import IO


@implementer(IFile)
@frozen
class File:
    basedir: Path = field(kw_only=True)
    file_path_info: FilePathInfo = field(kw_only=True)
    path: Path = field(kw_only=True)

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} {self.path}>"

    def exists(self) -> bool:
        return self.path.exists()

    def get_rel_rename(self) -> str:
        return self.path.relative_to(self.basedir).as_posix()

    def getsize(self) -> int | None:
        with suppress(OSError):
            return os.path.getsize(self.path)
        return None

    def open(self, mode: str) -> IO:
        return self.path.open(mode)

    def os_path(self) -> Path:
        return self.path

    def remove(self) -> list[str]:
        assert tmpsuffix_for_path(self.path) is None
        with suppress(OSError):
            os.remove(self.path)
        return [str(self.path.relative_to(self.basedir))]


@implementer(IDirtyFile)
@frozen
class DirtyFile(File):
    dst_path: Path = field(kw_only=True)

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} {self.path} {self.dst_path}>"

    def commit(self) -> list[str]:
        assert tmpsuffix_for_path(self.path) is not None
        rename(self.path, self.dst_path)
        return [str(self.dst_path.relative_to(self.basedir))]

    def drop(self) -> None:
        os.remove(self.path)

    def remove(self) -> list[str]:
        raise NotImplementedError


@provider(IDirtyFileFactory, IFileFactory)
class FSFactory:
    @classmethod
    def _make_path(cls, basedir: Path, relpath: RelPath) -> Path:
        return basedir / "+files" / relpath

    @classmethod
    def from_content(
        cls, basedir: Path, file_path_info: FilePathInfo, content_or_file: ContentOrFile
    ) -> IDirtyFile:
        path = cls._make_path(basedir, file_path_info.relpath)
        assert not path.name.endswith("-tmp")
        # use hash of path, pid and thread id to prevent conflicts
        key = f"{path}{os.getpid()}{threading.current_thread().ident}"
        digest = sha256(key.encode("utf-8")).hexdigest()
        if sys.platform == "win32":
            # on windows we have to shorten the digest, otherwise we reach
            # the 260 chars file path limit too quickly
            digest = digest[:8]
        dirty_file = DirtyFile(
            basedir=basedir,
            dst_path=path,
            file_path_info=file_path_info,
            path=path.with_name(f"{path.name}-{digest}-tmp"),
        )
        if hasattr(content_or_file, "devpi_srcpath"):
            dirty_file.path.parent.mkdir(parents=True, exist_ok=True)
            # Path.hardlink_to becomes available in Python 3.10
            os.link(content_or_file.devpi_srcpath, dirty_file.path)
        else:
            dirty_file.path.parent.mkdir(parents=True, exist_ok=True)
            with dirty_file.path.open("wb") as f:
                if isinstance(content_or_file, bytes):
                    f.write(content_or_file)
                else:
                    assert content_or_file.seekable()
                    content_or_file.seek(0)
                    shutil.copyfileobj(content_or_file, f)
        return dirty_file

    @classmethod
    def get_file(cls, basedir: Path, file_path_info: FilePathInfo) -> IFile:
        return File(
            basedir=basedir,
            file_path_info=file_path_info,
            path=cls._make_path(basedir, file_path_info.relpath),
        )


class FSIOFile(FSIOFileBase):
    file_factory = IFileFactory(FSFactory)
    dirtyfile_factory = IDirtyFileFactory(FSFactory)

    def _perform_crash_recovery(
        self, infos: Iterable[tuple[str, RelPath, FilePathInfo | None, bool]]
    ) -> None:
        basedir = self.basedir
        for rel_rename, relpath, _, is_deleted in infos:
            if is_deleted:
                path = FSFactory._make_path(basedir, relpath)
                with suppress(OSError):
                    path.unlink()
                    threadlog.warn("completed file-del from crashed tx: %s", path)
            else:
                dst = FSFactory._make_path(basedir, relpath)
                src = basedir / rel_rename
                if src.exists():
                    rename(src, dst)
                    threadlog.warn("completed file-commit from crashed tx: %s", dst)
                elif not dst.exists():
                    msg = f"missing file {dst}"
                    raise FileNotFoundError(msg)

    def rel_renames_needing_file_path_info(
        self, rel_renames: Iterable[str]
    ) -> dict[str, bool]:
        return dict.fromkeys(rel_renames, False)


@provider(IIOFileFactory)
def fsiofile_factory(conn: KeyFSConnWithClosing, settings: dict) -> FSIOFile:
    conn = cast(
        "KeyFSConn",
        conn.thing if isinstance(conn, closing) else conn,  # type: ignore[attr-defined]
    )
    base_path = Path(conn.storage.basedir)
    return FSIOFile(base_path, settings)
