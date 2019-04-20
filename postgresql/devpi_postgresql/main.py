from devpi_common.types import cached_property
from devpi_server.fileutil import dumps, loads
from devpi_server.log import threadlog, thread_push_log, thread_pop_log
from devpi_server.readonly import ReadonlyView
from devpi_server.readonly import ensure_deeply_readonly, get_mutable_deepcopy
from functools import partial
from pluggy import HookimplMarker
from repoze.lru import LRUCache
import contextlib
import os
import pg8000
import py
import time


devpiserver_hookimpl = HookimplMarker("devpiserver")


class Connection:
    def __init__(self, sqlconn, storage):
        self._sqlconn = sqlconn
        self.dirty_files = {}
        self.changes = {}
        self.storage = storage
        self._changelog_cache = storage._changelog_cache

    def __enter__(self):
        return self

    def __exit__(self, cls, val, tb):
        pass

    def close(self):
        self._sqlconn.close()
        del self._sqlconn
        del self.storage

    def commit(self):
        self._sqlconn.commit()

    @cached_property
    def last_changelog_serial(self):
        return self.db_read_last_changelog_serial()

    def db_read_last_changelog_serial(self):
        q = 'SELECT MAX(serial) FROM changelog LIMIT 1'
        c = self._sqlconn.cursor()
        c.execute(q)
        res = c.fetchone()[0]
        return -1 if res is None else res

    def db_read_typedkey(self, relpath):
        q = "SELECT keyname, serial FROM kv WHERE key = %s"
        c = self._sqlconn.cursor()
        c.execute(q, (relpath,))
        row = c.fetchone()
        if row is None:
            raise KeyError(relpath)
        return tuple(row[:2])

    def db_write_typedkey(self, relpath, name, next_serial):
        q = """
            INSERT INTO kv(key, keyname, serial)
                VALUES (%s, %s, %s)
            ON CONFLICT (key) DO UPDATE
                SET keyname = EXCLUDED.keyname, serial = EXCLUDED.serial;"""
        c = self._sqlconn.cursor()
        c.execute(q, (relpath, name, next_serial))
        c.close()

    def write_changelog_entry(self, serial, entry):
        threadlog.debug("writing changelog for serial %s", serial)
        data = dumps(entry)
        c = self._sqlconn.cursor()
        c.execute("INSERT INTO changelog (serial, data) VALUES (%s, %s)",
                  (serial, pg8000.Binary(data)))
        c.close()
        self._sqlconn.commit()

    def io_file_os_path(self, path):
        return None

    def io_file_exists(self, path):
        assert not os.path.isabs(path)
        c = self._sqlconn.cursor()
        q = "SELECT path FROM files WHERE path = %s"
        c.execute(q, (path,))
        result = c.fetchone()
        c.close()
        return result is not None

    def io_file_set(self, path, content):
        assert not os.path.isabs(path)
        assert not path.endswith("-tmp")
        c = self._sqlconn.cursor()
        q = """
            INSERT INTO files(path, size, data)
                VALUES (%s, %s, %s)
            ON CONFLICT (path) DO UPDATE
                SET size = EXCLUDED.size, data = EXCLUDED.data;"""
        c.execute(q, (path, len(content), pg8000.Binary(content)))
        c.close()
        self.dirty_files[path] = content

    def io_file_open(self, path):
        return py.io.BytesIO(self.io_file_get(path))

    def io_file_get(self, path):
        assert not os.path.isabs(path)
        c = self._sqlconn.cursor()
        q = "SELECT data FROM files WHERE path = %s"
        c.execute(q, (path,))
        content = c.fetchone()
        c.close()
        if content is None:
            raise IOError()
        return content[0]

    def io_file_size(self, path):
        assert not os.path.isabs(path)
        c = self._sqlconn.cursor()
        q = "SELECT size FROM files WHERE path = %s"
        c.execute(q, (path,))
        result = c.fetchone()
        c.close()
        if result is not None:
            return result[0]

    def io_file_delete(self, path):
        assert not os.path.isabs(path)
        c = self._sqlconn.cursor()
        q = "DELETE FROM files WHERE path = %s"
        c.execute(q, (path,))
        c.close()
        self.dirty_files[path] = None

    def get_raw_changelog_entry(self, serial):
        q = "SELECT data FROM changelog WHERE serial = %s"
        c = self._sqlconn.cursor()
        c.execute(q, (serial,))
        row = c.fetchone()
        c.close()
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

    def write_transaction(self):
        return Writer(self.storage, self)

    def commit_files_without_increasing_serial(self):
        self.commit()


class Storage:
    database = "devpi"
    host = "localhost"
    port = "5432"
    unix_sock = None
    user = "devpi"
    password = None

    def __init__(self, basedir, notify_on_commit, cache_size, settings=None):
        if settings is None:
            settings = {}
        for key in ("database", "host", "port", "unix_sock", "user", "password"):
            if key in settings:
                setattr(self, key, settings[key])
        self.basedir = basedir
        self._notify_on_commit = notify_on_commit
        self._changelog_cache = LRUCache(cache_size)  # is thread safe
        self.last_commit_timestamp = time.time()
        self.ensure_tables_exist()
        with self.get_connection() as conn:
            c = conn._sqlconn.cursor()
            c.execute("select max(serial) from changelog")
            row = c.fetchone()
            c.close()
            serial = row[0]
            if serial is None:
                self.next_serial = 0
            else:
                self.next_serial = serial + 1

    def perform_crash_recovery(self):
        pass

    def get_connection(self, closing=True, write=False):
        sqlconn = pg8000.connect(
            user=self.user,
            database=self.database,
            host=self.host,
            port=int(self.port),
            unix_sock=self.unix_sock,
            password=self.password,
            timeout=60)
        sqlconn.text_factory = bytes
        conn = Connection(sqlconn, self)
        if write:
            q = 'SELECT pg_advisory_xact_lock(1);'
            c = conn._sqlconn.cursor()
            c.execute(q)
        if closing:
            return contextlib.closing(conn)
        return conn

    def ensure_tables_exist(self):
        with self.get_connection() as conn:
            sqlconn = conn._sqlconn
            c = sqlconn.cursor()
            try:
                c.execute("select * from changelog limit 1")
                c.fetchall()
                c.execute("select * from kv limit 1")
                c.fetchall()
            except pg8000.ProgrammingError:
                sqlconn.rollback()
                threadlog.info("DB: Creating schema")
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
                        data BYTEA NOT NULL
                    )
                """)
                c.execute("""
                    CREATE TABLE files (
                        path TEXT PRIMARY KEY,
                        size INTEGER NOT NULL,
                        data BYTEA NOT NULL
                    )
                """)
                sqlconn.commit()
            finally:
                c.close()


@devpiserver_hookimpl
def devpiserver_storage_backend(settings):
    return dict(
        storage=partial(Storage, settings=settings),
        name="pg8000",
        description="Postgresql backend")


class Writer:
    def __init__(self, storage, conn):
        self.conn = conn
        self.storage = storage
        self.changes = {}

    def record_set(self, typedkey, value=None, back_serial=None):
        """ record setting typedkey to value (None means it's deleted) """
        assert not isinstance(value, ReadonlyView), value
        if back_serial is None:
            try:
                _, back_serial = self.conn.db_read_typedkey(typedkey.relpath)
            except KeyError:
                back_serial = -1
        self.conn.db_write_typedkey(typedkey.relpath, typedkey.name,
                                    self.storage.next_serial)
        # at __exit__ time we write out changes to the _changelog_cache
        # so we protect here against the caller modifying the value later
        value = get_mutable_deepcopy(value)
        self.changes[typedkey.relpath] = (typedkey.name, back_serial, value)

    def __enter__(self):
        self.log = thread_push_log("fswriter%s:" % self.storage.next_serial)
        return self

    def __exit__(self, cls, val, tb):
        thread_pop_log("fswriter%s:" % self.storage.next_serial)
        if cls is None:
            entry = self.changes, []
            self.conn.write_changelog_entry(self.storage.next_serial, entry)
            commit_serial = self.storage.next_serial
            self.storage.next_serial += 1
            message = "committed: keys: %s"
            args = [",".join(map(repr, list(self.changes)))]
            self.log.info(message, *args)

            self.storage._notify_on_commit(commit_serial)
        else:
            self.log.info("roll back at %s" % (self.storage.next_serial))
        del self.conn
        del self.storage
