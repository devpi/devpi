from .keyfs_sqlite_fs import Connection as BaseConnection
from .keyfs_sqlite_fs import Storage as BaseStorage
from .log import threadlog
import os
import py
import sqlite3


class Connection(BaseConnection):
    def io_file_os_path(self, path):
        return None

    def io_file_exists(self, path):
        assert not os.path.isabs(path)
        c = self._sqlconn.cursor()
        q = "SELECT path FROM files WHERE path = ?"
        c.execute(q, (path,))
        result = c.fetchone()
        c.close()
        return result is not None

    def io_file_set(self, path, content):
        assert not os.path.isabs(path)
        assert not path.endswith("-tmp")
        c = self._sqlconn.cursor()
        q = "INSERT OR REPLACE INTO files (path, size, data) VALUES (?, ?, ?)"
        c.execute(q, (path, len(content), sqlite3.Binary(content)))
        c.close()

    def io_file_open(self, path):
        return py.io.BytesIO(self.io_file_get(path))

    def io_file_get(self, path):
        assert not os.path.isabs(path)
        c = self._sqlconn.cursor()
        q = "SELECT data FROM files WHERE path = ?"
        c.execute(q, (path,))
        content = c.fetchone()
        c.close()
        if content is None:
            raise IOError()
        return bytes(content[0])

    def io_file_size(self, path):
        assert not os.path.isabs(path)
        c = self._sqlconn.cursor()
        q = "SELECT size FROM files WHERE path = ?"
        c.execute(q, (path,))
        result = c.fetchone()
        c.close()
        if result is not None:
            return result[0]

    def io_file_delete(self, path):
        assert not os.path.isabs(path)
        c = self._sqlconn.cursor()
        q = "DELETE FROM files WHERE path = ?"
        c.execute(q, (path,))
        c.close()


class Storage(BaseStorage):
    Connection = Connection

    def ensure_tables_exist(self):
        if self.sqlpath.exists():
            return
        with self.get_connection() as conn:
            threadlog.info("DB: Creating schema")
            c = conn._sqlconn.cursor()
            c.execute("""
                CREATE TABLE kv (
                    key TEXT NOT NULL PRIMARY KEY,
                    keyname TEXT,
                    serial INTEGER
                )
            """)
            c.execute("""
                CREATE TABLE changelog (
                    serial INTEGER PRIMARY KEY,
                    data BLOB NOT NULL
                )
            """)
            c.execute("""
                CREATE TABLE files (
                    path TEXT PRIMARY KEY,
                    size INTEGER NOT NULL,
                    data BLOB NOT NULL
                )
            """)


def devpiserver_storage_backend():
    return dict(
        storage=Storage,
        name="sqlite_db_files",
        description="SQLite backend with files in DB for testing only")
