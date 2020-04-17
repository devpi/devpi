from .config import hookimpl
from .fileutil import BytesForHardlink
from .keyfs_sqlite import BaseConnection
from .keyfs_sqlite import BaseStorage
from .log import threadlog, thread_push_log, thread_pop_log
from .readonly import ReadonlyView
from .readonly import get_mutable_deepcopy
from .fileutil import get_write_file_ensure_dir, rename, loads
from hashlib import sha256
import errno
import os
import re
import sys
import threading
import time


class DirtyFile(object):
    def __init__(self, path, content):
        self.path = path
        # use hash of path, pid and thread id to prevent conflicts
        key = "%s%i%i" % (
            path, os.getpid(), threading.current_thread().ident)
        digest = sha256(key.encode('utf-8')).hexdigest()
        if sys.platform == 'win32':
            # on windows we have to shorten the digest, otherwise we reach
            # the 260 chars file path limit too quickly
            digest = digest[:8]
        self.tmppath = '%s-%s-tmp' % (path, digest)
        if isinstance(content, BytesForHardlink):
            dirname = os.path.dirname(self.tmppath)
            if not os.path.exists(dirname):
                try:
                    os.makedirs(dirname)
                except IOError as e:
                    # ignore file exists errors
                    # one reason for that error is a race condition where
                    # another thread tries to create the same folder
                    if e.errno != errno.EEXIST:
                        raise
            os.link(content.devpi_srcpath, self.tmppath)
        else:
            with get_write_file_ensure_dir(self.tmppath) as f:
                f.write(content)


class Connection(BaseConnection):
    def rollback(self):
        BaseConnection.rollback(self)
        drop_dirty_files(self.dirty_files)

    def io_file_os_path(self, path):
        path = self._basedir.join(path).strpath
        if path in self.dirty_files:
            raise RuntimeError("Can't access file %s directly during transaction" % path)
        return path

    def io_file_exists(self, path):
        path = self._basedir.join(path).strpath
        if path in self.dirty_files:
            dirty_file = self.dirty_files[path]
            if dirty_file is None:
                return False
            path = dirty_file.tmppath
        return os.path.exists(path)

    def io_file_set(self, path, content):
        path = self._basedir.join(path).strpath
        assert not path.endswith("-tmp")
        self.dirty_files[path] = DirtyFile(path, content)

    def io_file_open(self, path):
        path = self._basedir.join(path).strpath
        if path in self.dirty_files:
            dirty_file = self.dirty_files[path]
            if dirty_file is None:
                raise IOError()
            path = dirty_file.tmppath
        return open(path, "rb")

    def io_file_get(self, path):
        path = self._basedir.join(path).strpath
        if path in self.dirty_files:
            dirty_file = self.dirty_files[path]
            if dirty_file is None:
                raise IOError()
            path = dirty_file.tmppath
        with open(path, "rb") as f:
            return f.read()

    def io_file_size(self, path):
        path = self._basedir.join(path).strpath
        if path in self.dirty_files:
            dirty_file = self.dirty_files[path]
            if dirty_file is None:
                return None
            path = dirty_file.tmppath
        try:
            return os.path.getsize(path)
        except OSError:
            return None

    def io_file_delete(self, path):
        path = self._basedir.join(path).strpath
        old = self.dirty_files.get(path)
        if old is not None:
            os.remove(old.tmppath)
        self.dirty_files[path] = None

    def write_transaction(self):
        return FSWriter(self.storage, self)

    def commit_files_without_increasing_serial(self):
        pending_renames = write_dirty_files(self.dirty_files)
        basedir = str(self.storage.basedir)
        rel_renames = list(make_rel_renames(basedir, pending_renames))
        files_commit, files_del = commit_renames(basedir, rel_renames)
        message = "wrote files without increasing serial: "
        args = []
        if files_commit:
            message += "%s"
            args.append(",".join(files_commit))
        if files_del:
            message += ", files_del: %s"
            args.append(",".join(files_del))
        if args:
            threadlog.debug(message, *args)


class Storage(BaseStorage):
    Connection = Connection
    db_filename = ".sqlite"

    def perform_crash_recovery(self):
        # get last changes and verify all renames took place
        with self.get_connection() as conn:
            if conn.last_changelog_serial == -1:
                return
            data = conn.get_raw_changelog_entry(conn.last_changelog_serial)
        changes, rel_renames = loads(data)
        check_pending_renames(str(self.basedir), rel_renames)

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
            conn.commit()


@hookimpl
def devpiserver_storage_backend(settings):
    return dict(
        storage=Storage,
        name="sqlite",
        description="SQLite backend with files on the filesystem",
        _test_markers=["storage_with_filesystem"])


class FSWriter:
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
            pending_renames = write_dirty_files(self.conn.dirty_files)

            changed_keys, files_commit, files_del = \
                self.commit_to_filesystem(pending_renames)

            # write out a nice commit entry to logging
            message = "committed: keys: %s"
            args = [",".join(map(repr, changed_keys))]
            if files_commit:
                message += ", files_commit: %s"
                args.append(",".join(files_commit))
            if files_del:
                message += ", files_del: %s"
                args.append(",".join(files_del))
            self.log.info("commited at %s", commit_serial)
            self.log.debug(message, *args)

            self.storage._notify_on_commit(commit_serial)
        else:
            drop_dirty_files(self.conn.dirty_files)
            self.conn.rollback()
            self.log.info("roll back at %s", commit_serial)

    def commit_to_filesystem(self, pending_renames):
        basedir = str(self.storage.basedir)
        rel_renames = list(
            make_rel_renames(basedir, pending_renames)
        )
        entry = self.changes, rel_renames
        self.conn.write_changelog_entry(self.next_serial, entry)
        self.conn.commit()

        # If we crash in the remainder, the next restart will
        # - call check_pending_renames which will replay any remaining
        #   renames from the changelog entry, and
        # - initialize next_serial from the max committed serial + 1
        files_commit, files_del = commit_renames(basedir, rel_renames)
        self.storage.last_commit_timestamp = time.time()
        return list(self.changes), files_commit, files_del


def drop_dirty_files(dirty_files):
    for path, dirty_file in dirty_files.items():
        if dirty_file is not None:
            os.remove(dirty_file.tmppath)


def write_dirty_files(dirty_files):
    pending_renames = []
    for path, dirty_file in dirty_files.items():
        if dirty_file is None:
            pending_renames.append((None, path))
        else:
            pending_renames.append((dirty_file.tmppath, path))
    return pending_renames


tmp_file_matcher = re.compile(r"(.*?)(-[0-9a-fA-F]{8,64})?(-tmp)$")


def tmpsuffix_for_path(path):
    # ends with -tmp and includes hash since temp files are written directly
    # to disk instead of being kept in memory
    m = tmp_file_matcher.match(path)
    if m is not None:
        if m.group(2):
            suffix = m.group(2) + m.group(3)
        else:
            suffix = m.group(3)
        return suffix


def check_pending_renames(basedir, pending_relnames):
    for relpath in pending_relnames:
        path = os.path.join(basedir, relpath)
        suffix = tmpsuffix_for_path(relpath)
        if suffix is not None:
            suffix_len = len(suffix)
            dst = path[:-suffix_len]
            if os.path.exists(path):
                rename(path, dst)
                threadlog.warn("completed file-commit from crashed tx: %s",
                               dst)
            else:
                if not os.path.exists(dst):
                    raise OSError("missing file %s" % dst)
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
        suffix = tmpsuffix_for_path(relpath)
        if suffix is not None:
            suffix_len = len(suffix)
            rename(path, path[:-suffix_len])
            files_commit.append(relpath[:-suffix_len])
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
            assert source.startswith(dest) and source.endswith("-tmp")
            yield source[len(basedir) + 1:]
        else:
            assert dest.startswith(basedir)
            yield dest[len(basedir) + 1:]
