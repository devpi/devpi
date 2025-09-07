from __future__ import annotations

from .keyfs_types import RelpathInfo
from contextlib import closing
from inspect import getfullargspec
from typing import TYPE_CHECKING
from typing import overload
from zope.interface import Attribute
from zope.interface import Interface
from zope.interface import classImplements
from zope.interface import implementer
from zope.interface.interface import adapter_hooks
from zope.interface.verify import verifyObject


if TYPE_CHECKING:
    from .keyfs_types import FilePathInfo
    from .keyfs_types import PTypedKey
    from .keyfs_types import Record
    from .keyfs_types import RelPath
    from .keyfs_types import TypedKey
    from collections.abc import Callable
    from collections.abc import Iterable
    from collections.abc import Iterator
    from contextlib import AbstractContextManager
    from types import TracebackType
    from typing import Any
    from typing import IO
    from typing import Literal
    from typing import Union

    ContentOrFile = Union[IO[bytes], bytes]


class IDBIOFileConnection(Interface):
    def commit_files_without_increasing_serial() -> None:
        """Writes any files which have been changed without
        increasing the serial."""

    def io_file_delete(path: FilePathInfo) -> None:
        """Deletes the file at path."""

    def io_file_exists(path: FilePathInfo) -> bool:
        """Returns True if file at path exists."""

    def io_file_get(path: FilePathInfo) -> bytes:
        """Returns binary content of the file at path."""

    def io_file_new_open(path: FilePathInfo) -> IO[bytes]:
        """Returns a new open file like object for binary writing."""

    def io_file_open(path: FilePathInfo) -> IO[bytes]:
        """Returns an open file like object for binary reading."""

    def io_file_os_path(path: FilePathInfo) -> str | None:
        """Returns the real path to the file if the storage is filesystem
        based, otherwise None."""

    def io_file_set(path: FilePathInfo, content_or_file: ContentOrFile) -> None:
        """Set the binary content of the file at path."""

    def io_file_size(path: FilePathInfo) -> int | None:
        """Returns the size of the file at path."""


class IIOFileFactory(Interface):
    def __call__(conn: IStorageConnection4, settings: dict) -> IIOFile:
        pass


class IIOFile(Interface):
    def __enter__() -> AbstractContextManager:
        pass

    def __exit__(  # noqa: PLE0302, PYI036
        cls: type[BaseException] | None,
        val: BaseException | None,  # noqa: PYI036
        tb: TracebackType | None,  # noqa: PYI036
    ) -> bool | None:
        pass

    def commit() -> None:
        """Commit changed files to storage."""

    def delete(path: FilePathInfo) -> None:
        """Deletes the file at path."""

    def exists(path: FilePathInfo) -> bool:
        """Returns True if file at path exists."""

    def get_content(path: FilePathInfo) -> bytes:
        """Returns binary content of the file at path."""

    def get_rel_renames() -> list[str]:
        """Returns deserialized rel_renames for given serial."""

    def is_dirty() -> bool:
        """Indicate whether there are any file changes pending."""

    def is_path_dirty(path: FilePathInfo) -> bool:
        """Indicate whether the real path to the file, if the storage is
        filesystem based, is dirty."""

    def new_open(path: FilePathInfo) -> IO[bytes]:
        """Returns a new open file like object for binary writing."""

    def open_read(path: FilePathInfo) -> IO[bytes]:
        """Returns an open file like object for binary reading."""

    def os_path(path: FilePathInfo) -> str | None:
        """Returns the real path to the file if the storage is filesystem
        based, otherwise None."""

    def perform_crash_recovery(
        iter_rel_renames: Callable[[], Iterable[RelPath]],
        iter_file_path_infos: Callable[[Iterable[RelPath]], Iterable[FilePathInfo]],
    ) -> None:
        """Perform recovery from crash during two phase commit."""

    def rollback() -> None:
        """Rollback changes to files."""

    def set_content(path: FilePathInfo, content_or_file: ContentOrFile) -> None:
        """Set the binary content of the file at path."""

    def size(path: FilePathInfo) -> int | None:
        """Returns the size of the file at path."""


class IStorage(Interface):
    basedir = Attribute(""" The base directory as py.path.local. """)

    last_commit_timestamp: float = Attribute("""
        The timestamp of the last commit. """)

    @overload
    def get_connection(
        *, closing: Literal[True], write: bool, timeout: float
    ) -> AbstractContextManager[Any]:
        pass

    @overload
    def get_connection(*, closing: Literal[False], write: bool, timeout: float) -> Any:
        pass

    def get_connection(
        *, closing: bool, write: bool, timeout: float
    ) -> Any | AbstractContextManager[Any]:
        """Returns a connection to the storage."""


class IStorageConnection(Interface):
    last_changelog_serial = Attribute("""
        Like db_read_last_changelog_serial, but cached on the class. """)

    def db_read_last_changelog_serial() -> int:
        """ Return last stored serial.
            Returns -1 if nothing is stored yet. """

    def db_read_typedkey(relpath: str) -> tuple[str, int]:
        """ Return key name and serial for given relpath.
            Raises KeyError if not found. """

    def get_changes(serial: int) -> dict:
        """ Returns deserialized readonly changes for given serial. """

    def get_raw_changelog_entry(serial: int) -> bytes | None:
        """ Returns serializes changes for given serial. """

    def io_file_delete(path: str) -> None:
        """ Deletes the file at path. """

    def io_file_exists(path: str) -> bool:
        """ Returns True if file at path exists. """

    def io_file_get(path: str) -> bytes:
        """ Returns binary content of the file at path. """

    def io_file_open(path: str) -> IO[bytes]:
        """ Returns an open file like object for binary reading. """

    def io_file_os_path(path: str) -> str | None:
        """ Returns the real path to the file if the storage is filesystem
            based, otherwise None. """

    def io_file_set(path: str, content: bytes) -> None:
        """ Set the binary content of the file at path. """

    def io_file_size(path: str) -> int | None:
        """ Returns the size of the file at path. """

    def commit_files_without_increasing_serial() -> None:
        """ Writes any files which have been changed without
            increasing the serial. """

    def write_transaction() -> AbstractContextManager:
        """Returns a context providing class with a IWriter2 interface."""


class IStorageConnection2(IStorageConnection):
    def get_relpath_at(relpath: str, serial: int) -> tuple[int, int, Any]:
        """ Get tuple of (last_serial, back_serial, value) for given relpath
            at given serial.
            Raises KeyError if not found. """

    def iter_relpaths_at(typedkeys: Iterable[Union[PTypedKey, TypedKey]], at_serial: int) -> Iterator[RelpathInfo]:
        """ Iterate over all relpaths of the given typed keys starting
            from at_serial until the first serial in the database. """


class IStorageConnection3(IStorageConnection2):
    def io_file_set(path: str, content_or_file: ContentOrFile) -> None:
        """ Set the binary content of the file at path. """

    def io_file_new_open(path: str) -> IO[bytes]:
        """ Returns a new open file like object for binary writing. """


class IStorageConnection4(Interface):
    last_changelog_serial: int = Attribute("""
        Like db_read_last_changelog_serial, but cached on the class. """)

    storage: IStorage = Attribute(""" The storage instance for this connection. """)

    def close() -> None:
        """Close the storage."""

    def db_read_last_changelog_serial() -> int:
        """Return last stored serial.
        Returns -1 if nothing is stored yet."""

    def db_read_typedkey(relpath: RelPath) -> tuple[str, int]:
        """Return key name and serial for given relpath.
        Raises KeyError if not found."""

    def get_changes(serial: int) -> dict:
        """Returns deserialized readonly changes for given serial."""

    def get_raw_changelog_entry(serial: int) -> bytes | None:
        """Returns serialized changes for given serial."""

    def get_rel_renames(serial: int) -> Iterable | None:
        """Returns deserialized rel_renames for given serial."""

    def get_relpath_at(relpath: RelPath, serial: int) -> tuple[int, int, Any]:
        """Get tuple of (last_serial, back_serial, value) for given relpath
        at given serial.
        Raises KeyError if not found."""

    def iter_relpaths_at(
        typedkeys: Iterable[Union[PTypedKey, TypedKey]], at_serial: int
    ) -> Iterator[RelpathInfo]:
        """Iterate over all relpaths of the given typed keys starting
        from at_serial until the first serial in the database."""

    def write_transaction() -> AbstractContextManager:
        """Returns a context providing class with a IWriter2 interface."""


class IWriter(Interface):
    commit_serial = Attribute("""
        The current to be commited serial set when entering the context manager. """)

    def __enter__() -> AbstractContextManager:
        pass

    def __exit__(  # noqa: PLE0302, PYI036
        cls: type[BaseException] | None,
        val: BaseException | None,  # noqa: PYI036
        tb: TracebackType | None,  # noqa: PYI036
    ) -> bool | None:
        pass

    def record_set(
        typedkey: Union[PTypedKey, TypedKey], value: Any, back_serial: int
    ) -> None:
        pass


class IWriter2(Interface):
    commit_serial = Attribute("""
        The current to be commited serial set when entering the context manager. """)

    def __enter__() -> AbstractContextManager:
        pass

    def __exit__(  # noqa: PLE0302 PYI036
        cls: type[BaseException] | None,
        val: BaseException | None,  # noqa: PYI036
        tb: TracebackType | None,  # noqa: PYI036
    ) -> bool | None:
        pass

    def records_set(records: Iterable[Record]) -> None:
        pass

    def set_rel_renames(rel_renames: list[str]) -> None:
        pass


# some adapters for legacy plugins


def unwrap_connection_obj(obj: Any) -> Any:
    if isinstance(obj, closing):
        obj = obj.thing  # type: ignore[attr-defined]
    return obj


def get_connection_class(obj: Any) -> type:
    return unwrap_connection_obj(obj).__class__


def verify_connection_interface(obj: Any) -> None:
    verifyObject(IStorageConnection4, unwrap_connection_obj(obj))


_adapters = {}


def _register_adapter(func: Callable) -> None:
    spec = getfullargspec(func)
    iface = spec.annotations[spec.args[0]]
    if isinstance(iface, str):
        iface = globals()[iface]
    if iface in _adapters:
        msg = f"Adapter for {iface.getName()!r} already registered."
        raise RuntimeError(msg)
    _adapters[iface] = func


@implementer(IDBIOFileConnection)
class IOFileConnectionAdapter:
    def __init__(self, conn: Any) -> None:
        # any storage connection which needs this adapter
        # is a legacy one and we can get IStorageConnection3 for it
        self.conn = IStorageConnection3(conn)
        self.commit_files_without_increasing_serial = (
            conn.commit_files_without_increasing_serial
        )
        self.dirty_files = conn.dirty_files
        self.storage = conn.storage

    def io_file_delete(self, path: FilePathInfo) -> None:
        return self.conn.io_file_delete(path.relpath)

    def io_file_exists(self, path: FilePathInfo) -> bool:
        return self.conn.io_file_exists(path.relpath)

    def io_file_get(self, path: FilePathInfo) -> bytes:
        return self.conn.io_file_get(path.relpath)

    def io_file_new_open(self, path: FilePathInfo) -> IO[bytes]:
        return self.conn.io_file_new_open(path.relpath)

    def io_file_open(self, path: FilePathInfo) -> IO[bytes]:
        return self.conn.io_file_open(path.relpath)

    def io_file_os_path(self, path: FilePathInfo) -> str | None:
        return self.conn.io_file_os_path(path.relpath)

    def io_file_set(self, path: FilePathInfo, content_or_file: ContentOrFile) -> None:
        return self.conn.io_file_set(path.relpath, content_or_file)

    def io_file_size(self, path: FilePathInfo) -> int | None:
        return self.conn.io_file_size(path.relpath)


@_register_adapter
def adapt_idbiofileconnection(iface: IDBIOFileConnection, obj: Any) -> Any:
    obj = unwrap_connection_obj(obj)
    obj = IOFileConnectionAdapter(obj)
    verifyObject(iface, obj)
    return obj


@_register_adapter
def adapt_istorage(iface: IStorage, obj: Any) -> Any:
    cls = obj.__class__
    orig_get_connection = cls.get_connection
    spec = getfullargspec(orig_get_connection)

    def get_connection(
        self: Any,
        *,
        closing: bool = True,
        write: bool = False,
        timeout: float = 30,  # noqa: ARG001 - backward compatibility
    ) -> Any:
        return orig_get_connection(self, closing=closing, write=write)

    if "timeout" not in spec.args:
        cls.get_connection = get_connection
    classImplements(cls, iface)  # type: ignore[misc]
    verifyObject(iface, obj)
    return obj


@_register_adapter
def adapt_istorageconnection(iface: IStorageConnection, obj: Any) -> Any:
    _obj = unwrap_connection_obj(obj)
    cls = get_connection_class(_obj)
    # any storage connection which needs to be adapted to this
    # interface is a legacy one and we can say that it provides
    # the original interface directly
    classImplements(cls, iface)  # type: ignore[misc]
    # make sure the object now actually provides this interface
    verifyObject(iface, _obj)
    return obj


@_register_adapter
def adapt_istorageconnection2(iface: IStorageConnection2, obj: Any) -> Any:
    from .fileutil import loads
    from .keyfs import get_relpath_at
    # first make sure the old connection interface is implemented
    obj = IStorageConnection(obj)
    _obj = unwrap_connection_obj(obj)
    cls = get_connection_class(_obj)

    def iter_relpaths_at(self: Any, typedkeys: Iterable[Union[PTypedKey, TypedKey]], at_serial: int) -> Iterator[RelpathInfo]:
        keynames = frozenset(k.name for k in typedkeys)
        seen = set()
        for serial in range(at_serial, -1, -1):
            raw_entry = self.get_raw_changelog_entry(serial)
            changes = loads(raw_entry)[0]
            for relpath, (keyname, back_serial, val) in changes.items():
                if keyname not in keynames:
                    continue
                if relpath not in seen:
                    seen.add(relpath)
                    yield RelpathInfo(
                        relpath=relpath, keyname=keyname,
                        serial=serial, back_serial=back_serial,
                        value=val)

    # now add fallback methods directly to the class
    cls.get_relpath_at = get_relpath_at  # type: ignore[attr-defined]
    cls.iter_relpaths_at = iter_relpaths_at  # type: ignore[attr-defined]
    # and add the interface
    classImplements(cls, iface)  # type: ignore[misc]
    # make sure the object now actually provides this interface
    verifyObject(iface, _obj)
    return obj


@_register_adapter
def adapt_istorageconnection3(iface: IStorageConnection3, obj: Any) -> Any:
    from .log import threadlog
    # first make sure the old connection interface is implemented
    obj = IStorageConnection2(obj)
    _obj = unwrap_connection_obj(obj)
    cls = get_connection_class(_obj)

    def io_file_new_open(self: Any, path: str) -> IO[bytes]:
        """ Fallback method for legacy storage connections. """
        from tempfile import TemporaryFile
        return TemporaryFile()

    def io_file_set(
        self: Any, path: str, content_or_file: ContentOrFile, _io_file_set: Callable
    ) -> None:
        """ Fallback method wrapper for legacy storage connections. """
        # _io_file_set is from the original class
        if not isinstance(content_or_file, bytes):
            content_or_file.seek(0)
            content_or_file = content_or_file.read()
        if len(content_or_file) > 1048576:
            threadlog.warn(
                "Got content with %.1f megabytes in memory while setting content for %s",
                len(content_or_file) / 1048576, path)
        return _io_file_set(self, path, content_or_file)

    # now add fallback method directly to the class
    cls.io_file_new_open = io_file_new_open  # type: ignore[attr-defined]
    orig_io_file_set = cls.io_file_set  # type: ignore[attr-defined]

    # we need another wrapper to pass in the io_file_set from original class
    # for some reason a partial doesn't work here
    def _io_file_set(self: Any, path: str, content_or_file: ContentOrFile) -> None:
        return io_file_set(self, path, content_or_file, _io_file_set=orig_io_file_set)

    cls.io_file_set = _io_file_set  # type: ignore[attr-defined]
    # and add the interface
    classImplements(cls, iface)  # type: ignore[misc]
    # make sure the object now actually provides this interface
    verifyObject(iface, _obj)
    return obj


@_register_adapter
def adapt_istorageconnection4(iface: IStorageConnection4, obj: Any) -> Any:
    from .fileutil import loads

    # first make sure the old connection interface is implemented
    obj = IStorageConnection3(obj)
    _obj = unwrap_connection_obj(obj)
    cls = get_connection_class(_obj)

    def close(self: Any) -> None:
        pass

    if not hasattr(cls, "close"):
        cls.close = close  # type: ignore[attr-defined]

    def _get_rel_renames(self: Any, serial: int) -> Iterable | None:
        if serial == -1:
            return None
        data = self.get_raw_changelog_entry(serial)
        (_changes, rel_renames) = loads(data)
        return rel_renames

    cls.get_rel_renames = _get_rel_renames  # type: ignore[attr-defined]

    orig_write_transaction = cls.write_transaction  # type: ignore[attr-defined]

    def _write_transaction(self: Any, *, io_file: Any = None) -> AbstractContextManager:  # noqa: ARG001
        return orig_write_transaction(self)

    cls.write_transaction = _write_transaction  # type: ignore[attr-defined]
    # and add the interface
    classImplements(cls, iface)  # type: ignore[misc]
    # make sure the object now actually provides this interface
    verifyObject(iface, _obj)
    return obj


@_register_adapter
def adapt_iwriter(iface: IWriter, obj: Any) -> Any:
    # any writer which needs to be adapted to this interface is a
    # legacy one and we can say that it provides the original
    # interface directly
    cls = obj.__class__
    classImplements(cls, iface)  # type: ignore[misc]
    # make sure the object now actually provides this interface
    verifyObject(iface, obj)
    return obj


@_register_adapter
def adapt_iwriter2(iface: IWriter2, obj: Any) -> Any:
    # first make sure the old writer interface is implemented
    obj = IWriter(obj)
    cls = obj.__class__

    # now add fallback method directly to the class
    def _records_set(self: Any, records: Iterable[Record]) -> None:
        for record in records:
            self.record_set(record.key, record.value, record.back_serial)

    cls.records_set = _records_set

    def _set_rel_renames(self: Any, rel_renames: list[str]) -> None:
        pass

    cls.set_rel_renames = _set_rel_renames
    # and add the interface
    classImplements(cls, iface)  # type: ignore[misc]
    # make sure the object now actually provides this interface
    verifyObject(iface, obj)
    return obj


@adapter_hooks.append
def adapt(iface: Interface, obj: Any) -> Any:
    if iface in _adapters:
        return _adapters[iface](iface, obj)
    msg = f"don't know how to adapt {obj!r} to {iface.getName()!r}."  # type: ignore[attr-defined]
    raise ValueError(msg)
