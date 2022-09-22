from .keyfs_types import PTypedKey, RelpathInfo, TypedKey
from contextlib import closing
from typing import Any, BinaryIO, ContextManager, Iterator, List, Optional
from typing import Tuple, Type, Union
from zope.interface import Attribute
from zope.interface import Interface
from zope.interface import classImplements
from zope.interface.interface import adapter_hooks
from zope.interface.verify import verifyObject


class IStorageConnection(Interface):
    last_changelog_serial = Attribute("""
        Like db_read_last_changelog_serial, but cached on the class. """)

    def db_read_last_changelog_serial() -> int:
        """ Return last stored serial.
            Returns -1 if nothing is stored yet. """

    def db_read_typedkey(relpath: str) -> Tuple[str, int]:
        """ Return key name and serial for given relpath.
            Raises KeyError if not found. """

    def get_changes(serial: int) -> dict:
        """ Returns deserialized readonly changes for given serial. """

    def get_raw_changelog_entry(serial: int) -> Optional[bytes]:
        """ Returns serializes changes for given serial. """

    def io_file_delete(path: str) -> None:
        """ Deletes the file at path. """

    def io_file_exists(path: str) -> bool:
        """ Returns True if file at path exists. """

    def io_file_get(path: str) -> bytes:
        """ Returns binary content of the file at path. """

    def io_file_open(path: str) -> BinaryIO:
        """ Returns an open file like object for binary reading. """

    def io_file_os_path(path: str) -> Optional[str]:
        """ Returns the real path to the file if the storage is filesystem
            based, otherwise None. """

    def io_file_set(path: str, content: bytes) -> None:
        """ Set the binary content of the file at path. """

    def io_file_size(path: str) -> Optional[int]:
        """ Returns the size of the file at path. """

    def commit_files_without_increasing_serial() -> None:
        """ Writes any files which have been changed without
            increasing the serial. """

    def write_transaction() -> ContextManager:
        """ Returns a context providing class with a record_set method. """


class IStorageConnection2(IStorageConnection):
    def get_relpath_at(relpath: str, serial: int) -> Any:
        """ Get tuple of (last_serial, back_serial, value) for given relpath
            at given serial.
            Raises KeyError if not found. """

    def iter_relpaths_at(typedkeys: List[Union[PTypedKey, TypedKey]], at_serial: int) -> Iterator[RelpathInfo]:
        """ Iterate over all relpaths of the given typed keys starting
            from at_serial until the first serial in the database. """


class IStorageConnection3(IStorageConnection2):
    def io_file_set(path: str, content_or_file: Union[bytes, BinaryIO]) -> None:
        """ Set the binary content of the file at path. """

    def io_file_new_open(path: str) -> BinaryIO:
        """ Returns a new open file like object for binary writing. """


# some adapters for legacy plugins


def unwrap_connection_obj(obj: Any) -> Any:
    if isinstance(obj, closing):
        obj = obj.thing  # type: ignore
    return obj


def get_connection_class(obj: Any) -> Type:
    return unwrap_connection_obj(obj).__class__


def verify_connection_interface(obj: Any) -> None:
    verifyObject(IStorageConnection2, unwrap_connection_obj(obj))


@adapter_hooks.append
def adapt(iface: IStorageConnection, obj: Any) -> Any:
    # this is not traditional adaption which would return a new object,
    # but for performance reasons we directly patch the class, so the next
    # time no adaption call is necessary
    if iface is IStorageConnection:
        _obj = unwrap_connection_obj(obj)
        cls = get_connection_class(_obj)
        # any storage connection which needs to be adapted to this
        # interface is a legacy one and we can say that it provides
        # the original interface directly
        classImplements(cls, IStorageConnection)  # type: ignore
        # make sure the object now actually provides this interface
        verifyObject(IStorageConnection, _obj)
        return obj
    elif iface is IStorageConnection2:
        from .keyfs import get_relpath_at
        from .keyfs import iter_relpaths_at
        # first make sure the old connection interface is implemented
        obj = IStorageConnection(obj)
        _obj = unwrap_connection_obj(obj)
        cls = get_connection_class(_obj)
        # now add fallback methods directly to the class
        cls.get_relpath_at = get_relpath_at
        cls.iter_relpaths_at = iter_relpaths_at
        # and add the interface
        classImplements(cls, IStorageConnection2)  # type: ignore
        # make sure the object now actually provides this interface
        verifyObject(IStorageConnection2, _obj)
        return obj
    elif iface is IStorageConnection3:
        from .keyfs import io_file_new_open
        from .keyfs import io_file_set
        # first make sure the old connection interface is implemented
        obj = IStorageConnection2(obj)
        _obj = unwrap_connection_obj(obj)
        cls = get_connection_class(_obj)
        # now add fallback method directly to the class
        cls.io_file_new_open = io_file_new_open
        orig_io_file_set = cls.io_file_set

        # we need another wrapper to pass in the io_file_set from original class
        # for some reason a partial doesn't work here
        def _io_file_set(self: Any, path: str, content_or_file: Union[bytes, BinaryIO]) -> None:
            return io_file_set(self, path, content_or_file, _io_file_set=orig_io_file_set)

        cls.io_file_set = _io_file_set
        # and add the interface
        classImplements(cls, IStorageConnection3)  # type: ignore
        # make sure the object now actually provides this interface
        verifyObject(IStorageConnection3, _obj)
        return obj
