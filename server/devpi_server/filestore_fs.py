from __future__ import annotations

from .filestore_fs_base import FSIOFileBase
from .fileutil import rename
from .interfaces import IIOFileFactory
from .log import threadlog
from .markers import Deleted
from contextlib import closing
from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING
from typing import cast
from zope.interface import provider
import os
import re


if TYPE_CHECKING:
    from .keyfs import KeyFSConn
    from .keyfs import KeyFSConnWithClosing
    from .keyfs_types import FilePathInfo
    from .keyfs_types import RelPath
    from collections.abc import Callable
    from collections.abc import Iterable


class FSIOFile(FSIOFileBase):
    def _commit(self, msg: str) -> None:
        rel_renames = self.iter_rel_renames()
        (files_commit, files_del) = self.write_dirty_files(rel_renames)
        if files_commit or files_del:
            threadlog.debug(msg, LazyChangesFormatter({}, files_commit, files_del))

    def _make_path(self, path: FilePathInfo) -> str:
        return str(self.basedir / "+files" / path.relpath)

    def iter_pending_renames(self) -> Iterable[tuple[str | None, str]]:
        for relpath, dirty_file in self._dirty_files.items():
            _path = str(self.basedir / "+files" / relpath)
            if isinstance(dirty_file, Deleted):
                yield (None, _path)
            else:
                yield (dirty_file.tmppath, _path)

    def iter_rel_renames(self) -> Iterable[str]:
        return make_rel_renames(str(self.basedir), self.iter_pending_renames())

    def perform_crash_recovery(
        self,
        iter_rel_renames: Callable[[], Iterable[RelPath]],
        iter_file_path_infos: Callable[[Iterable[RelPath]], Iterable[FilePathInfo]],  # noqa: ARG002 - API
    ) -> None:
        rel_renames = list(iter_rel_renames())
        if rel_renames:
            check_pending_renames(str(self.basedir), rel_renames)

    def write_dirty_files(
        self, rel_renames: Iterable[str]
    ) -> tuple[list[str], list[str]]:
        basedir = str(self.basedir)
        # If we crash in the remainder, the next restart will
        # - call check_pending_renames which will replay any remaining
        #   renames from the changelog entry, and
        # - initialize next_serial from the max committed serial + 1
        result = commit_renames(basedir, rel_renames)
        self._dirty_files.clear()
        return result


class LazyChangesFormatter:
    __slots__ = ("files_commit", "files_del", "keys")

    def __init__(
        self,
        changes: dict,
        files_commit: Iterable[str],
        files_del: Iterable[str],
    ) -> None:
        self.files_commit = files_commit
        self.files_del = files_del
        self.keys = changes.keys()

    def __str__(self) -> str:
        msg = []
        if self.keys:
            msg.append(f"keys: {','.join(repr(c) for c in self.keys)}")
        if self.files_commit:
            msg.append(f"files_commit: {','.join(self.files_commit)}")
        if self.files_del:
            msg.append(f"files_del: {','.join(self.files_del)}")
        return ", ".join(msg)


def check_pending_renames(basedir: str, pending_relnames: Iterable[str]) -> None:
    for relpath in pending_relnames:
        path = os.path.join(basedir, relpath)
        suffix = tmpsuffix_for_path(relpath)
        if suffix is not None:
            suffix_len = len(suffix)
            dst = path[:-suffix_len]
            if os.path.exists(path):
                rename(path, dst)
                threadlog.warn("completed file-commit from crashed tx: %s", dst)
            elif not os.path.exists(dst):
                msg = f"missing file {dst}"
                raise OSError(msg)
        else:
            with suppress(OSError):
                os.remove(path)  # was already removed
                threadlog.warn("completed file-del from crashed tx: %s", path)


def commit_renames(
    basedir: str,
    pending_renames: Iterable[str],
) -> tuple[list[str], list[str]]:
    files_del = []
    files_commit = []
    for relpath in pending_renames:
        path = os.path.join(basedir, relpath)
        suffix = tmpsuffix_for_path(relpath)
        if suffix is not None:
            suffix_len = len(suffix)
            rename(path, path[:-suffix_len])
            files_commit.append(relpath[:-suffix_len])
        else:
            with suppress(OSError):
                os.remove(path)
            files_del.append(relpath)
    return (files_commit, files_del)


@provider(IIOFileFactory)
def fsiofile_factory(conn: KeyFSConnWithClosing, settings: dict) -> FSIOFile:
    conn = cast(
        "KeyFSConn",
        conn.thing if isinstance(conn, closing) else conn,  # type: ignore[attr-defined]
    )
    base_path = Path(conn.storage.basedir)
    return FSIOFile(base_path, settings)


def make_rel_renames(
    basedir: str,
    pending_renames: Iterable[tuple[str | None, str]],
) -> Iterable[str]:
    for source, dest in pending_renames:
        if source is not None:
            assert source.startswith(dest)
            assert source.endswith("-tmp")
            yield source[len(basedir) + 1 :]
        else:
            assert dest.startswith(basedir)
            yield dest[len(basedir) + 1 :]


tmp_file_matcher = re.compile(r"(.*?)(-[0-9a-fA-F]{8,64})?(-tmp)$")


def tmpsuffix_for_path(path: str) -> str | None:
    # ends with -tmp and includes hash since temp files are written directly
    # to disk instead of being kept in memory
    m = tmp_file_matcher.match(path)
    if m is not None:
        return m.group(2) + m.group(3) if m.group(2) else m.group(3)
    return None
