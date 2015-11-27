from .log import threadlog, thread_push_log, thread_pop_log
from .readonly import ReadonlyView
from .readonly import ensure_deeply_readonly, get_mutable_deepcopy
from .fileutil import (
    get_write_file_ensure_dir, rename, dumps, loads
)

from repoze.lru import LRUCache
import contextlib
import os
import py
import sqlite3
import time


class Connection:
    def __init__(self, sqlconn, basedir, storage):
        self._sqlconn = sqlconn
        self._basedir = basedir
        self.dirty_files = {}
        self.storage = storage
        self._changelog_cache = storage._changelog_cache

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

    def write_changelog_entry(self, serial, entry):
        threadlog.debug("writing changelog for serial %s", serial)
        data = dumps(entry)
        self._sqlconn.execute(
            "INSERT INTO changelog (serial, data) VALUES (?, ?)",
            (serial, sqlite3.Binary(data)))
        self._sqlconn.commit()

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

    def write_transaction(self):
        return FSWriter(self.storage, self)


class Storage:
    Connection = Connection

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

    def perform_crash_recovery(self):
        if self.next_serial > 0:
            # get last changes and verify all renames took place
            with self.get_connection() as conn:
                data = conn.get_raw_changelog_entry(self.next_serial - 1)
            changes, rel_renames = loads(data)
            check_pending_renames(str(self.basedir), rel_renames)

    def get_connection(self, closing=True):
        sqlconn = sqlite3.connect(str(self.sqlpath), timeout=60)
        conn = self.Connection(sqlconn, self.basedir, self)
        conn.text_factory = bytes
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


def devpiserver_storage_backend():
    return dict(
        storage=Storage,
        name="sqlite",
        description="SQLite backend with files on the filesystem",
        _test_markers=["storage_with_filesystem"])


class FSWriter:
    def __init__(self, storage, conn):
        self.conn = conn
        self.storage = storage
        self._pending_renames = []
        self.changes = {}

    def record_set(self, typedkey, value=None):
        """ record setting typedkey to value (None means it's deleted) """
        assert not isinstance(value, ReadonlyView), value
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
        pending_renames = []
        if cls is None:
            for path, content in self.conn.dirty_files.items():
                if content is None:
                    assert path.exists()
                    pending_renames.append((None, dest))
                else:
                    tmppath = path + "-tmp"
                    with get_write_file_ensure_dir(tmppath) as f:
                        f.write(content)
                    pending_renames.append((tmppath, path))

            changed_keys, files_commit, files_del = \
                self.commit_to_filesystem(pending_renames)
            commit_serial = self.storage.next_serial - 1

            # write out a nice commit entry to logging
            message = "committed: keys: %s"
            args = [",".join(map(repr, changed_keys))]
            if files_commit:
                message += ", files_commit: %s"
                args.append(",".join(files_commit))
            if files_del:
                message += ", files_del: %s"
                args.append(",".join(files_del))
            self.log.info(message, *args)

            self.storage._notify_on_commit(commit_serial)
        else:
            self.log.info("roll back at %s" %(self.storage.next_serial))

    def commit_to_filesystem(self, pending_renames):
        basedir = str(self.storage.basedir)
        rel_renames = list(
            make_rel_renames(basedir, pending_renames)
        )
        entry = self.changes, rel_renames
        self.conn.write_changelog_entry(self.storage.next_serial, entry)

        # If we crash in the remainder, the next restart will
        # - call check_pending_renames which will replay any remaining
        #   renames from the changelog entry, and
        # - initialize next_serial from the max committed serial + 1
        files_commit, files_del = commit_renames(basedir, rel_renames)
        self.storage.next_serial += 1
        self.storage.last_commit_timestamp = time.time()
        return list(self.changes), files_commit, files_del


def check_pending_renames(basedir, pending_relnames):
    for relpath in pending_relnames:
        path = os.path.join(basedir, relpath)
        if relpath.endswith("-tmp"):
            if os.path.exists(path):
                rename(path, path[:-4])
                threadlog.warn("completed file-commit from crashed tx: %s",
                               path[:-4])
            else:
                assert os.path.exists(path[:-4])
        else:
            try:
                os.remove(path)  # was already removed
                threadlog.warn("completed file-del from crashed tx: %s", path)
            except OSError:
                pass

def commit_renames(basedir, pending_renames):
    files_del = []
    files_commit = []
    for relpath in pending_renames:
        path = os.path.join(basedir, relpath)
        if relpath.endswith("-tmp"):
            rename(path, path[:-4])
            files_commit.append(relpath[:-4])
        else:
            try:
                os.remove(path)
            except OSError:
                pass
            files_del.append(relpath)
    return files_commit, files_del

def make_rel_renames(basedir, pending_renames):
    # produce a list of strings which are
    # - paths relative to basedir
    # - if they have "-tmp" at the end it means they should be renamed
    #   to the path without the "-tmp" suffix
    # - if they don't have "-tmp" they should be removed
    for source, dest in pending_renames:
        if source is not None:
            assert source == dest + "-tmp"
            yield source[len(basedir)+1:]
        else:
            assert dest.startswith(basedir)
            yield dest[len(basedir)+1:]

