from .config import hookimpl
from .interfaces import IStorageConnection4
from .keyfs_sqlite import BaseConnection
from .keyfs_sqlite import BaseStorage
from zope.interface import implementer


@implementer(IStorageConnection4)
class Connection(BaseConnection):
    def _write_dirty_files(self):
        return ([], [])


class Storage(BaseStorage):
    Connection = Connection
    db_filename = ".sqlite"
    expected_schema = dict(
        index=dict(
            kv_serial_idx="""
                CREATE INDEX kv_serial_idx ON kv (serial);
            """),
        table=dict(
            changelog="""
                CREATE TABLE changelog (
                    serial INTEGER PRIMARY KEY,
                    data BLOB NOT NULL
                )
            """,
            kv="""
                CREATE TABLE kv (
                    key TEXT NOT NULL PRIMARY KEY,
                    keyname TEXT,
                    serial INTEGER
                )
            """))


@hookimpl
def devpiserver_storage_backend(settings):
    return dict(
        storage=Storage,
        name="sqlite",
        description="SQLite backend with files on the filesystem",
        db_filestore=False,
        settings=settings,
        _test_markers=["storage_with_filesystem"],
    )
