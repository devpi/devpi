from devpi_common.types import cached_property
from .config import hookimpl
from .fileutil import dumps, loads
from .log import threadlog, thread_push_log, thread_pop_log
from .readonly import ReadonlyView
from .readonly import ensure_deeply_readonly, get_mutable_deepcopy
from repoze.lru import LRUCache
import contextlib
import os
import py
import sqlite3
import time


class BaseConnection:
    def __init__(self, sqlconn, basedir, storage):
        self._sqlconn = sqlconn
        self._basedir = basedir
        self.dirty_files = {}
        self.storage = storage
        self._changelog_cache = storage._changelog_cache

    def close(self):
        self._sqlconn.close()

    def commit(self):
        self._sqlconn.commit()

    def rollback(self):
        self._sqlconn.rollback()

    @cached_property
    def last_changelog_serial(self):
        return self.db_read_last_changelog_serial()

    def db_read_last_changelog_serial(self):
        q = 'SELECT MAX(_ROWID_) FROM "changelog" LIMIT 1'
        res = self._sqlconn.execute(q).fetchone()[0]
        return -1 if res is None else res

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

    def get_raw_changelog_entry(self, serial):
        q = "SELECT data FROM changelog WHERE serial = ?"
        row = self._sqlconn.execute(q, (serial,)).fetchone()
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
            assert isinstance(changes, ReadonlyView)
            self._changelog_cache.put(serial, changes)
        return changes


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
        self.dirty_files[path] = True

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
        self.dirty_files[path] = None

    def write_transaction(self):
        return Writer(self.storage, self)

    def commit_files_without_increasing_serial(self):
        self.commit()


class BaseStorage(object):
    def __init__(self, basedir, notify_on_commit, cache_size):
        self.basedir = basedir
        self.sqlpath = self.basedir.join(self.db_filename)
        self._notify_on_commit = notify_on_commit
        self._changelog_cache = LRUCache(cache_size)  # is thread safe
        self.last_commit_timestamp = time.time()
        self.ensure_tables_exist()

    def _get_sqlconn_uri_kw(self, uri):
        return sqlite3.connect(
            uri, timeout=60, isolation_level=None, uri=True)

    def _get_sqlconn_uri(self, uri):
        return sqlite3.connect(
            uri, timeout=60, isolation_level=None)

    def _get_sqlconn_path(self, uri):
        return sqlite3.connect(
            self.sqlpath.strpath, timeout=60, isolation_level=None)

    def _get_sqlconn(self, uri):
        # we will try different connection methods and overwrite _get_sqlconn
        # with the first successful one
        try:
            # the uri keyword is only supported from Python 3.4 onwards and
            # possibly other Python implementations
            conn = self._get_sqlconn_uri_kw(uri)
            # remember for next time
            self._get_sqlconn = self._get_sqlconn_uri_kw
            return conn
        except TypeError as e:
            if e.args and 'uri' in e.args[0] and 'keyword argument' in e.args[0]:
                threadlog.warn(
                    "The uri keyword for 'sqlite3.connect' isn't supported by "
                    "this Python version.")
            else:
                raise
        except sqlite3.OperationalError as e:
            threadlog.warn("%s" % e)
            threadlog.warn(
                "The installed version of sqlite3 doesn't seem to support "
                "the uri keyword for 'sqlite3.connect'.")
        except sqlite3.NotSupportedError:
            threadlog.warn(
                "The installed version of sqlite3 doesn't support the uri "
                "keyword for 'sqlite3.connect'.")
        try:
            # sqlite3 might be compiled with default URI support
            conn = self._get_sqlconn_uri(uri)
            # remember for next time
            self._get_sqlconn = self._get_sqlconn_uri
            return conn
        except sqlite3.OperationalError as e:
            # log the error and switch to using the path
            threadlog.warn("%s" % e)
            threadlog.warn(
                "Opening the sqlite3 db without options in URI. There is a "
                "higher possibility of read/write conflicts between "
                "threads, causing slowdowns due to retries.")
            conn = self._get_sqlconn_path(uri)
            # remember for next time
            self._get_sqlconn = self._get_sqlconn_path
            return conn

    def get_connection(self, closing=True, write=False):
        # we let the database serialize all writers at connection time
        # to play it very safe (we don't have massive amounts of writes).
        mode = "ro"
        if write:
            mode = "rw"
        if not self.sqlpath.exists():
            mode = "rwc"
        uri = "file:%s?mode=%s" % (self.sqlpath, mode)
        sqlconn = self._get_sqlconn(uri)
        if write:
            start_time = time.time()
            while 1:
                try:
                    sqlconn.execute("begin immediate")
                    break
                except sqlite3.OperationalError:
                    # another thread may be writing, give it a chance to finish
                    time.sleep(0)
                    if time.time() - start_time > 5:
                        # if it takes this long, something is wrong
                        raise
        conn = self.Connection(sqlconn, self.basedir, self)
        if closing:
            return contextlib.closing(conn)
        return conn


class Storage(BaseStorage):
    Connection = Connection
    db_filename = ".sqlite_db"

    def perform_crash_recovery(self):
        pass

    def ensure_tables_exist(self):
        if self.sqlpath.exists():
            return
        with self.get_connection(write=True) as conn:
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
            conn.commit()


@hookimpl
def devpiserver_storage_backend(settings):
    return dict(
        storage=Storage,
        name="sqlite_db_files",
        description="SQLite backend with files in DB for testing only")


@hookimpl
def devpiserver_metrics(request):
    result = []
    xom = request.registry["xom"]
    storage = xom.keyfs._storage
    if not isinstance(storage, BaseStorage):
        return result
    cache = getattr(storage, '_changelog_cache', None)
    if cache is None:
        return result
    result.extend([
        ('devpi_server_storage_cache_evictions', 'counter', cache.evictions),
        ('devpi_server_storage_cache_hits', 'counter', cache.hits),
        ('devpi_server_storage_cache_lookups', 'counter', cache.lookups),
        ('devpi_server_storage_cache_misses', 'counter', cache.misses),
        ('devpi_server_storage_cache_size', 'gauge', cache.size)])
    return result


class Writer:
    def __init__(self, storage, conn):
        self.conn = conn
        self.storage = storage
        self.changes = {}
        self.next_serial = conn.last_changelog_serial + 1

    def record_set(self, typedkey, value=None, back_serial=None):
        """ record setting typedkey to value (None means it's deleted) """
        assert not isinstance(value, ReadonlyView), value
        if back_serial is None:
            try:
                _, back_serial = self.conn.db_read_typedkey(typedkey.relpath)
            except KeyError:
                back_serial = -1
        self.conn.db_write_typedkey(typedkey.relpath, typedkey.name, self.next_serial)
        # at __exit__ time we write out changes to the _changelog_cache
        # so we protect here against the caller modifying the value later
        value = get_mutable_deepcopy(value)
        self.changes[typedkey.relpath] = (typedkey.name, back_serial, value)

    def __enter__(self):
        self.log = thread_push_log("fswriter%s:" % self.next_serial)
        return self

    def __exit__(self, cls, val, tb):
        commit_serial = self.next_serial
        thread_pop_log("fswriter%s:" % commit_serial)
        if cls is None:
            entry = self.changes, []
            self.conn.write_changelog_entry(commit_serial, entry)
            self.conn.commit()
            message = "committed: keys: %s"
            args = [",".join(map(repr, list(self.changes)))]
            self.log.info("commited at %s", commit_serial)
            self.log.debug(message, *args)

            self.storage._notify_on_commit(commit_serial)
        else:
            self.conn.rollback()
            self.log.info("roll back at %s", commit_serial)
