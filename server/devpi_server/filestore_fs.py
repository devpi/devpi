from .fileutil import get_write_file_ensure_dir
from .fileutil import rename
from .log import threadlog
from contextlib import suppress
from hashlib import sha256
from zope.interface import Interface
import os
import re
import shutil
import sys
import threading


class IStorageFile(Interface):
    """ Marker interface. """


class DirtyFile:
    def __init__(self, path):
        self.path = path
        # use hash of path, pid and thread id to prevent conflicts
        key = f"{path}{os.getpid()}{threading.current_thread().ident}"
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
                # ignore file exists errors
                # one reason for that error is a race condition where
                # another thread tries to create the same folder
                with suppress(FileExistsError):
                    os.makedirs(dirname)
            os.link(content_or_file.devpi_srcpath, self.tmppath)
        else:
            with get_write_file_ensure_dir(self.tmppath) as f:
                if isinstance(content_or_file, bytes):
                    f.write(content_or_file)
                else:
                    assert content_or_file.seekable()
                    content_or_file.seek(0)
                    shutil.copyfileobj(content_or_file, f)
        return self


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
            with suppress(OSError):
                os.remove(path)  # was already removed
                threadlog.warn("completed file-del from crashed tx: %s", path)


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
            with suppress(OSError):
                os.remove(path)
            files_del.append(relpath)
    return (files_commit, files_del)


def make_rel_renames(basedir, pending_renames):
    # produce a list of strings which are
    # - paths relative to basedir
    # - if they have "-tmp" at the end it means they should be renamed
    #   to the path without the "-tmp" suffix
    # - if they don't have "-tmp" they should be removed
    for source, dest in pending_renames:
        if source is not None:
            assert source.startswith(dest)
            assert source.endswith("-tmp")
            yield source[len(basedir) + 1:]
        else:
            assert dest.startswith(basedir)
            yield dest[len(basedir) + 1:]


tmp_file_matcher = re.compile(r"(.*?)(-[0-9a-fA-F]{8,64})?(-tmp)$")


def tmpsuffix_for_path(path):
    # ends with -tmp and includes hash since temp files are written directly
    # to disk instead of being kept in memory
    m = tmp_file_matcher.match(path)
    if m is not None:
        return m.group(2) + m.group(3) if m.group(2) else m.group(3)
    return None
