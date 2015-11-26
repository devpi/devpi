from .keyfs import dumps, loads
from .log import threadlog
from .readonly import ReadonlyView
from .readonly import ensure_deeply_readonly
from repoze.lru import LRUCache
import contextlib
import os
import py
import sqlite3
import time


class Connection:
    def __init__(self, sqlconn, basedir):
        self._sqlconn = sqlconn
        self._basedir = basedir
        self.dirty_files = {}

    def __enter__(self):
        return self

    def __exit__(self, cls, val, tb):
        pass

    def close(self):
        self._sqlconn.close()

    def db_read_typedkey(self, relpath):
        q = "SELECT keyname, serial FROM kv WHERE key = ?"
        c = self._sqlconn.cursor()
        row = c.execute(q, (relpath,)).fetchone()
        if row is None:
            raise KeyError(relpath)
        return tuple(row[:2])

    def db_write_typedkey(self, relpath, name, next_serial):
        q = "INSERT OR REPLACE INTO kv (key, keyname, serial) VALUES (?, ?, ?)"
        self._sqlconn.execute(q, (relpath, name, next_serial))

    def write_changelog_entry(self, serial, entry):
        threadlog.debug("writing changelog for serial %s", serial)
        data = dumps(entry)
        self._sqlconn.execute(
            "INSERT INTO changelog (serial, data) VALUES (?, ?)",
            (serial, sqlite3.Binary(data)))
        self._sqlconn.commit()

    def io_file_os_path(self, path):
        path = self._basedir.join(path).strpath
        if path in self.dirty_files:
            raise RuntimeError("Can't access file %s directly during transaction" % path)
        return path

    def io_file_exists(self, path):
        path = self._basedir.join(path).strpath
        try:
            return self.dirty_files[path] is not None
        except KeyError:
            return os.path.exists(path)

    def io_file_set(self, path, content):
        path = self._basedir.join(path).strpath
        assert not path.endswith("-tmp")
        self.dirty_files[path] = content

    def io_file_open(self, path):
        path = self._basedir.join(path).strpath
        try:
            f = py.io.BytesIO(self.dirty_files[path])
        except KeyError:
            f = open(path, "rb")
        return f

    def io_file_get(self, path):
        path = self._basedir.join(path).strpath
        try:
            content = self.dirty_files[path]
        except KeyError:
            with open(path, "rb") as f:
                return f.read()
        if content is None:
            raise IOError()
        return content

    def io_file_size(self, path):
        path = self._basedir.join(path).strpath
        try:
            content = self.dirty_files[path]
        except KeyError:
            try:
                return os.path.getsize(path)
            except OSError:
                return None
        if content is not None:
            return len(content)

    def io_file_delete(self, path):
        path = self._basedir.join(path).strpath
        self.dirty_files[path] = None


class Storage:
    def __init__(self, basedir, notify_on_commit, cache_size):
        self.basedir = basedir
        self.sqlpath = self.basedir.join(".sqlite")
        self._notify_on_commit = notify_on_commit
        self._changelog_cache = LRUCache(cache_size)  # is thread safe
        self.last_commit_timestamp = time.time()
        self.ensure_tables_exist()
        with self.get_connection() as conn:
            row = conn._sqlconn.execute("select max(serial) from changelog").fetchone()
            serial = row[0]
            if serial is None:
                self.next_serial = 0
            else:
                self.next_serial = serial + 1

    def get_raw_changelog_entry(self, serial):
        q = "SELECT data FROM changelog WHERE serial = ?"
        with self.get_connection() as conn:
            conn.text_factory = bytes
            row = conn._sqlconn.execute(q, (serial,)).fetchone()
            if row is not None:
                return bytes(row[0])
            return None

    def get_changes(self, serial):
        changes = self._changelog_cache.get(serial)
        if changes is None:
            data = self.get_raw_changelog_entry(serial)
            changes, rel_renames = loads(data)
            # make values in changes read only so no calling site accidentally
            # modifies data
            changes = ensure_deeply_readonly(changes)
            self.cache_commit_changes(serial, changes)
        return changes

    def cache_commit_changes(self, serial, changes):
        assert isinstance(changes, ReadonlyView)
        self._changelog_cache.put(serial, changes)

    def get_connection(self, closing=True):
        sqlconn = sqlite3.connect(str(self.sqlpath), timeout=60)
        conn = Connection(sqlconn, self.basedir)
        if closing:
            return contextlib.closing(conn)
        return conn

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
