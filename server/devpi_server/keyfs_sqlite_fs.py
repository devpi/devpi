from .config import hookimpl
from .interfaces import IStorageConnection3
from .keyfs_sqlite import BaseConnection
from .keyfs_sqlite import BaseStorage
from .log import threadlog
from .fileutil import get_write_file_ensure_dir, rename, loads
from hashlib import sha256
from zope.interface import Interface
from zope.interface import alsoProvides
from zope.interface import implementer
import errno
import os
import re
import shutil
import sys
import threading


class IStorageFile(Interface):
    """ Marker interface. """


class DirtyFile(object):
    def __init__(self, path):
        self.path = path
        # use hash of path, pid and thread id to prevent conflicts
        key = "%s%i%i" % (
            path, os.getpid(), threading.current_thread().ident)
        digest = sha256(key.encode('utf-8')).hexdigest()
        if sys.platform == 'win32':
            # on windows we have to shorten the digest, otherwise we reach
            # the 260 chars file path limit too quickly
            digest = digest[:8]
        self.tmppath = f"{path}-{digest}-tmp"

    def __repr__(self):
        return f"<{self.__class__.__name__} {self.path}>"

    @classmethod
    def from_content(cls, path, content_or_file):
        self = DirtyFile(path)
        if hasattr(content_or_file, "devpi_srcpath"):
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
            os.link(content_or_file.devpi_srcpath, self.tmppath)
        else:
            with get_write_file_ensure_dir(self.tmppath) as f:
                if not isinstance(content_or_file, bytes) and not callable(getattr(content_or_file, "seekable", None)):
                    content_or_file = content_or_file.read()
                    if len(content_or_file) > 1048576:
                        threadlog.warn(
                            "Read %.1f megabytes into memory in keyfs_sqlite_fs from_content for %s, because of unseekable file",
                            len(content_or_file) / 1048576, path)
                if isinstance(content_or_file, bytes):
                    f.write(content_or_file)
                else:
                    content_or_file.seek(0)
                    shutil.copyfileobj(content_or_file, f)
        return self


@implementer(IStorageConnection3)
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

    def io_file_set(self, path, content_or_file):
        path = self._basedir.join(path).strpath
        assert not path.endswith("-tmp")
        if IStorageFile.providedBy(content_or_file):
            self.dirty_files[path] = DirtyFile(path)
        else:
            self.dirty_files[path] = DirtyFile.from_content(path, content_or_file)

    def io_file_new_open(self, path):
        path = self._basedir.join(path).strpath
        assert not path.endswith("-tmp")
        assert not self.io_file_exists(path)
        f = get_write_file_ensure_dir(DirtyFile(path).tmppath)
        alsoProvides(f, IStorageFile)
        return f

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
            data = f.read()
            if len(data) > 1048576:
                threadlog.warn(
                    "Read %.1f megabytes into memory in io_file_get for %s",
                    len(data) / 1048576, path)
            return data

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

    def _get_rel_renames(self):
        pending_renames = write_dirty_files(self.dirty_files)
        basedir = str(self.storage.basedir)
        return list(make_rel_renames(basedir, pending_renames))

    def _write_dirty_files(self, rel_renames):
        basedir = str(self.storage.basedir)
        # If we crash in the remainder, the next restart will
        # - call check_pending_renames which will replay any remaining
        #   renames from the changelog entry, and
        # - initialize next_serial from the max committed serial + 1
        result = commit_renames(basedir, rel_renames)
        self.dirty_files.clear()
        return result

    def _drop_dirty_files(self):
        drop_dirty_files(self.dirty_files)
        self.dirty_files.clear()

    def commit_files_without_increasing_serial(self):
        rel_renames = self._get_rel_renames()
        (files_commit, files_del) = self._write_dirty_files(rel_renames)
        if files_commit or files_del:
            threadlog.debug(
                "wrote files without increasing serial: %s",
                LazyChangesFormatter({}, files_commit, files_del))


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

    def perform_crash_recovery(self):
        # get last changes and verify all renames took place
        with self.get_connection() as conn:
            if conn.last_changelog_serial == -1:
                return
            data = conn.get_raw_changelog_entry(conn.last_changelog_serial)
        changes, rel_renames = loads(data)
        check_pending_renames(str(self.basedir), rel_renames)


@hookimpl
def devpiserver_storage_backend(settings):
    return dict(
        storage=Storage,
        name="sqlite",
        description="SQLite backend with files on the filesystem",
        _test_markers=["storage_with_filesystem"])


class LazyChangesFormatter:
    __slots__ = ('files_commit', 'files_del', 'keys')

    def __init__(self, changes, files_commit, files_del):
        self.files_commit = files_commit
        self.files_del = files_del
        self.keys = changes.keys()

    def __str__(self):
        msg = []
        if self.keys:
            msg.append(f"keys: {','.join(repr(c) for c in self.keys)}")
        if self.files_commit:
            msg.append(f"files_commit: {','.join(self.files_commit)}")
        if self.files_del:
            msg.append(f"files_del: {','.join(self.files_del)}")
        return ", ".join(msg)


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
            elif not os.path.exists(dst):
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
