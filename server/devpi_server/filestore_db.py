from __future__ import annotations

from .interfaces import IDBIOFileConnection
from .interfaces import IIOFile
from .interfaces import IIOFileFactory
from typing import TYPE_CHECKING
from zope.interface import implementer
from zope.interface import provider
from zope.interface.verify import verifyObject


if TYPE_CHECKING:
    from collections.abc import Callable
    from collections.abc import Iterable
    from types import TracebackType
    from typing import Any
    from typing_extensions import Self


@implementer(IIOFile)
@provider(IIOFileFactory)
class DBIOFile:
    def __init__(self, conn: Any) -> None:
        _conn = IDBIOFileConnection(conn)
        verifyObject(IDBIOFileConnection, _conn)
        self._dirty_files = conn.dirty_files
        self.commit = _conn.commit_files_without_increasing_serial
        self.delete = _conn.io_file_delete
        self.exists = _conn.io_file_exists
        self.get_content = _conn.io_file_get
        self._get_rel_renames = getattr(conn, "_get_rel_renames", None)
        self.new_open = _conn.io_file_new_open
        self.open_read = _conn.io_file_open
        self.os_path = _conn.io_file_os_path
        self._perform_crash_recovery = getattr(
            conn.storage, "perform_crash_recovery", None
        )
        self.rollback = getattr(conn, "_drop_dirty_files", self._rollback)
        self.set_content = _conn.io_file_set
        self.size = _conn.io_file_size

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        cls: type[BaseException] | None,
        val: BaseException | None,
        tb: TracebackType | None,
    ) -> bool:
        if cls is not None:
            self.rollback()
            return False
        return True

    def get_rel_renames(self) -> list:
        if self._get_rel_renames is None:
            return []
        return self._get_rel_renames()

    def is_dirty(self) -> bool:
        return bool(self._dirty_files)

    def perform_crash_recovery(
        self,
        iter_rel_renames: Callable[[], Iterable[str]],  # noqa: ARG002 - API
    ) -> None:
        if self._perform_crash_recovery is not None:
            self._perform_crash_recovery()

    def _rollback(self) -> None:
        pass
