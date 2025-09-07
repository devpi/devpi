from __future__ import annotations

from .compat import SpooledTemporaryFile
from .interfaces import IIOFile
from .keyfs_types import FilePathInfo
from .keyfs_types import RelPath
from .log import threadlog
from .markers import Deleted
from .markers import deleted
from collections import defaultdict
from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING
from zope.interface import Attribute
from zope.interface import Interface
from zope.interface import implementer
import re


if TYPE_CHECKING:
    from .interfaces import ContentOrFile
    from collections.abc import Callable
    from collections.abc import Iterable
    from types import TracebackType
    from typing import IO
    from typing import Literal
    from typing_extensions import Self


class IFile(Interface):
    file_path_info: FilePathInfo = Attribute("The FilePathInfo for this dirty file.")

    def exists() -> bool:
        """The file exists."""

    def get_rel_rename() -> str:
        """The rel_rename for crash recovery."""

    def getsize() -> int | None:
        """The size of the file."""

    def open(mode: Literal["rb"]) -> IO[bytes]:
        """Open the file."""

    def os_path() -> Path:
        """The canonical path to the file on the filesystem."""

    def remove() -> list[str]:
        """Remove the file."""


class IDirtyFile(IFile):
    def commit() -> list[str]:
        """Commit the dirty file."""

    def drop() -> None:
        """Drop the dirty file."""


class IDirtyFileFactory(Interface):
    def from_content(
        basedir: Path, file_path_info: FilePathInfo, content_or_file: ContentOrFile
    ) -> IDirtyFile:
        """Create dirty file instance."""


class IFileFactory(Interface):
    def get_file(basedir: Path, file_path_info: FilePathInfo) -> IFile:
        """Return file."""


@implementer(IIOFile)
class FSIOFileBase:
    _dirty_files: dict[RelPath, IDirtyFile | Deleted]
    _relpath_file_path_info_map: defaultdict[RelPath, set[FilePathInfo]]
    file_factory: IFileFactory
    dirtyfile_factory: IDirtyFileFactory

    def __init__(self, base_path: Path, settings: dict) -> None:
        self.settings = settings
        self.basedir = base_path
        self._dirty_files = {}
        self._relpath_file_path_info_map = defaultdict(set)

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
        self._dirty_files.clear()
        self._relpath_file_path_info_map.clear()
        return True

    def _commit(self, msg: str) -> None:
        # If we crash in the remainder, the next restart will
        # - call perform_crash_recovery which will replay any remaining
        #   changes from the changelog entry, and
        # - initialize next_serial from the max committed serial + 1
        _relpath_file_path_info_map = self._relpath_file_path_info_map
        basedir = self.basedir
        files_del = []
        files_commit = []
        for relpath, dirty_file in self._dirty_files.items():
            (file_path_info,) = _relpath_file_path_info_map[relpath]
            if isinstance(dirty_file, Deleted):
                fp = self.file_factory.get_file(basedir, file_path_info)
                files_del.extend(fp.remove())
            else:
                files_commit.extend(dirty_file.commit())
        if files_commit or files_del:
            threadlog.debug(msg, LazyChangesFormatter({}, files_commit, files_del))

    def delete(self, path: FilePathInfo) -> None:
        assert isinstance(path, FilePathInfo)
        old = self._dirty_files.get(path.relpath, deleted)
        if not isinstance(old, Deleted):
            old.drop()
        self._dirty_files[path.relpath] = deleted
        self._relpath_file_path_info_map[path.relpath].add(path)

    def exists(self, path: FilePathInfo) -> bool:
        assert isinstance(path, FilePathInfo)
        fp: IFile
        if path.relpath in self._dirty_files:
            dirty_file = self._dirty_files[path.relpath]
            if isinstance(dirty_file, Deleted):
                return False
            fp = dirty_file
        else:
            fp = self.file_factory.get_file(self.basedir, path)
        return fp.exists()

    def get_content(self, path: FilePathInfo) -> bytes:
        assert isinstance(path, FilePathInfo)
        fp: IFile
        if path.relpath in self._dirty_files:
            dirty_file = self._dirty_files[path.relpath]
            if isinstance(dirty_file, Deleted):
                raise FileNotFoundError(path.relpath)
            fp = dirty_file
        else:
            fp = self.file_factory.get_file(self.basedir, path)
        with fp.open("rb") as f:
            data = f.read()
            if len(data) > 1048576:
                threadlog.warn(
                    "Read %.1f megabytes into memory in get_content for %s",
                    len(data) / 1048576,
                    f.name,
                )
            return data

    def is_dirty(self) -> bool:
        return bool(self._dirty_files)

    def is_path_dirty(self, path: FilePathInfo) -> bool:
        return path.relpath in self._dirty_files

    def new_open(self, path: FilePathInfo) -> IO[bytes]:
        assert isinstance(path, FilePathInfo)
        assert not self.exists(path)
        return SpooledTemporaryFile(dir=str(self.basedir), max_size=1048576)

    def open_read(self, path: FilePathInfo) -> IO[bytes]:
        assert isinstance(path, FilePathInfo)
        fp: IFile
        if path.relpath in self._dirty_files:
            dirty_file = self._dirty_files[path.relpath]
            if isinstance(dirty_file, Deleted):
                raise FileNotFoundError(path.relpath)
            fp = dirty_file
        else:
            fp = self.file_factory.get_file(self.basedir, path)
        return fp.open("rb")

    def os_path(self, path: FilePathInfo) -> str:
        assert isinstance(path, FilePathInfo)
        return str(self.file_factory.get_file(self.basedir, path).os_path())

    def set_content(self, path: FilePathInfo, content_or_file: ContentOrFile) -> None:
        assert isinstance(path, FilePathInfo)
        self._dirty_files[path.relpath] = self.dirtyfile_factory.from_content(
            self.basedir, path, content_or_file
        )
        self._relpath_file_path_info_map[path.relpath].add(path)

    def size(self, path: FilePathInfo) -> int | None:
        assert isinstance(path, FilePathInfo)
        fp: IFile
        if path.relpath in self._dirty_files:
            dirty_file = self._dirty_files[path.relpath]
            if isinstance(dirty_file, Deleted):
                return None
            fp = dirty_file
        else:
            fp = self.file_factory.get_file(self.basedir, path)
        with suppress(OSError):
            return fp.getsize()
        return None

    def commit(self) -> None:
        self._commit("wrote files without increasing serial: %s")
        self._dirty_files.clear()
        self._relpath_file_path_info_map.clear()

    def iter_rel_renames(self) -> Iterable[str]:
        _relpath_file_path_info_map = self._relpath_file_path_info_map
        basedir = self.basedir
        for relpath, dirty_file in self._dirty_files.items():
            (file_path_info,) = _relpath_file_path_info_map[relpath]
            if isinstance(dirty_file, Deleted):
                yield self.file_factory.get_file(
                    basedir, file_path_info
                ).get_rel_rename()
            else:
                yield dirty_file.get_rel_rename()

    def get_rel_renames(self) -> list[str]:
        # produce a list of strings which are
        # - paths relative to basedir
        # - if they have "-tmp" at the end it means they should be renamed
        #   to the path without the "-tmp" suffix
        # - if they don't have "-tmp" they should be removed
        return list(self.iter_rel_renames())

    def perform_crash_recovery(
        self,
        iter_rel_renames: Callable[[], Iterable[RelPath]],
        iter_file_path_infos: Callable[[Iterable[RelPath]], Iterable[FilePathInfo]],
    ) -> None:
        rel_rename_relpath_is_deleted_map = {
            rel_rename: (
                RelPath(
                    Path(
                        rel_rename
                        if (suffix := tmpsuffix_for_path(rel_rename)) is None
                        else rel_rename.removesuffix(suffix)
                    )
                    .as_posix()
                    .removeprefix("+files/")
                ),
                suffix is None,
            )
            for rel_rename in iter_rel_renames()
        }
        rel_renames_needing_file_path_info_map = (
            self.rel_renames_needing_file_path_info(rel_rename_relpath_is_deleted_map)
        )
        relpath_file_path_info_map = {
            file_path_info.relpath: file_path_info
            for file_path_info in iter_file_path_infos(
                (
                    relpath
                    for rel_rename, (
                        relpath,
                        _,
                    ) in rel_rename_relpath_is_deleted_map.items()
                    if rel_renames_needing_file_path_info_map[rel_rename]
                )
            )
        }
        self._perform_crash_recovery(
            (
                (
                    rel_rename,
                    relpath,
                    relpath_file_path_info_map.get(relpath),
                    is_deleted,
                )
                for rel_rename, (
                    relpath,
                    is_deleted,
                ) in rel_rename_relpath_is_deleted_map.items()
            )
        )

    def _perform_crash_recovery(
        self, infos: Iterable[tuple[str, RelPath, FilePathInfo | None, bool]]
    ) -> None:
        raise NotImplementedError

    def rel_renames_needing_file_path_info(
        self, rel_renames: Iterable[str]
    ) -> dict[str, bool]:
        raise NotImplementedError

    def rollback(self) -> None:
        for dirty_file in self._dirty_files.values():
            if not isinstance(dirty_file, Deleted):
                dirty_file.drop()
        self._dirty_files.clear()
        self._relpath_file_path_info_map.clear()


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


tmp_file_matcher = re.compile(r"(.*?)(-[0-9a-fA-F]{8,64})?(-tmp)$")


def tmpsuffix_for_path(path: Path | str) -> str | None:
    # ends with -tmp and includes hash since temp files are written directly
    # to disk instead of being kept in memory
    name = path.name if isinstance(path, Path) else path
    m = tmp_file_matcher.match(name)
    if m is not None:
        return m.group(2) + m.group(3) if m.group(2) else m.group(3)
    return None
