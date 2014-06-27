"""
filesystem key/value storage with support for storing and retrieving
basic python types based on parametrizable keys.  Multiple
read Transactions can execute concurrently while at most one
write Transaction is ongoing.  Each Transaction will see a consistent
view of key/values refering to the point in time it was started,
independent from any future changes.
"""
from __future__ import unicode_literals
import re
import contextlib
import py
from . import mythread
from .log import threadlog, thread_push_log, thread_pop_log
import os
import sys

from execnet.gateway_base import Unserializer, _Serializer
from devpi_common.types import cached_property


_nodefault = object()

def load(io):
    return Unserializer(io, strconfig=(False, False)).load(versioned=False)

def dump(obj, io):
    return _Serializer(io.write).save(obj)


def read_int_from_file(path, default=0):
    try:
        with open(path, "rb") as f:
            return int(f.read())
    except IOError:
        return default

def write_int_to_file(val, path):
    tmp_path = path + "-tmp"
    with get_write_file_ensure_dir(tmp_path) as f:
        f.write(str(val).encode("utf-8"))
    rename(tmp_path, path)

def load_from_file(path, default=_nodefault):
    try:
        with open(path, "rb") as f:
            return load(f)
    except IOError:
        if default is _nodefault:
            raise
        return default

def dump_to_file(value, path):
    tmp_path = path + "-tmp"
    with get_write_file_ensure_dir(tmp_path) as f:
        dump(value, f)
    rename(tmp_path, path)

def get_write_file_ensure_dir(path):
    try:
        return open(path, "wb")
    except IOError:
        dirname = os.path.dirname(path)
        if os.path.exists(dirname):
            raise
        os.makedirs(dirname)
        return open(path, "wb")


class Filesystem:
    def __init__(self, basedir, notify_on_commit):
        self.basedir = basedir
        self._notify_on_commit = notify_on_commit
        self.path_next_serial = str(basedir.join(".nextserial"))
        self.path_changelogdir = basedir.ensure(".changelog", dir=1)
        self.next_serial = read_int_from_file(self.path_next_serial)
        self._last_commit_cache = None

    def write_transaction(self):
        return FSWriter(self)

    def get_from_transaction_entry(self, serial, relpath):
        return self.get_changelog_entry(serial).get(relpath)

    def get_raw_changelog_entry(self, serial):
        p = self.path_changelogdir.join(str(serial))
        try:
            with p.open("rb") as f:
                return f.read()
        except py.error.Error:
            return None

    def get_changelog_entry(self, serial):
        cache = self._last_commit_cache
        if cache is not None and cache[0] == serial:
            return cache[1]
        p = self.path_changelogdir.join(str(serial))
        return load_from_file(str(p))

    def cache_commit_entry(self, serial, changes):
        # setattr is atomic
        self._last_commit_cache = serial, changes

class FSWriter:
    def __init__(self, fs):
        self.fs = fs
        self.pending_renames = []
        self.changes = {}

    def _direct_write(self, path, val):
        tmpfile = path + "-tmp"
        with tmpfile.open("wb") as f:
            dump(val, f)
        tmpfile.rename(path)

    def record_set(self, typedkey, value=None):
        """ record setting typedkey to value (None means it's deleted) """
        relpath = typedkey.relpath
        target_path = typedkey.filepath
        tmp_path = target_path + ".tmp"
        next_serial = self.fs.next_serial
        name, back_serial = load_from_file(target_path, (typedkey.name, -1))
        with get_write_file_ensure_dir(tmp_path) as f:
            dump((typedkey.name, next_serial), f)
        # we later write out changes to the last_commit_cache, need to be careful
        # that the caller of the transaction doesn't alter the value
        # after we return.
        value = copy_if_mutable(value)
        self.changes[relpath] = (typedkey.name, back_serial, value)
        self.pending_renames.append((tmp_path, target_path))

    def record_rename_file(self, source, dest):
        assert dest
        self.pending_renames.append((source, dest))

    def __enter__(self):
        self.log = thread_push_log("fswriter%s:" % self.fs.next_serial)
        return self

    def __exit__(self, cls, val, tb):
        thread_pop_log("fswriter%s:" % self.fs.next_serial)
        if cls is None:
            assert self.pending_renames, "commit cannot be empty"
            self.commit_to_filesystem()
            commit_serial = self.fs.next_serial - 1
            size_basedir = len(str(self.fs.basedir))
            changed = [x[1][size_basedir:] for x in self.pending_renames]
            self.log.info("committed: %s", ",".join(changed))
            self.fs.cache_commit_entry(commit_serial, self.changes)
            self.fs._notify_on_commit(commit_serial)
        else:
            while self.pending_renames:
                source, dest = self.pending_renames.pop()
                if source is not None:
                    os.remove(source)
            self.log.info("roll back at %s" %(self.fs.next_serial))

    def commit_to_filesystem(self):
        # XXX assumption: we don't crash in the middle of this function
        p = self.fs.path_changelogdir.join(str(self.fs.next_serial))
        assert not p.exists(), (  # XXX recover
                    "change entry %s already exists, unclean shutdown?" %
                    self.fs.next_serial)
        self._direct_write(p, self.changes)

        # do all renames and removes
        for source, dest in self.pending_renames:
            if source is None:
                try:
                    os.remove(dest)
                except OSError:
                    pass
            else:
                rename(source, dest)

        # finally increment the serial and write it out
        self.fs.next_serial += 1
        write_int_to_file(self.fs.next_serial, self.fs.path_next_serial)


def rename(source, dest):
    try:
        os.rename(source, dest)
    except OSError:
        destdir = os.path.dirname(dest)
        if not os.path.exists(destdir):
            os.makedirs(destdir)
        if sys.platform == "win32" and os.path.exists(dest):
            os.remove(dest)
        os.rename(source, dest)


class TxNotificationThread:
    def __init__(self, keyfs):
        self.keyfs = keyfs
        self.cv_new_transaction = mythread.threading.Condition()
        self.cv_new_event_serial = mythread.threading.Condition()
        self.event_serial_path = str(self.keyfs.basedir.join(".event_serial"))
        self._on_key_change = {}

    def on_key_change(self, key, subscriber):
        assert not mythread.has_active_thread(self), (
               "cannot register handlers after thread has started")
        keyname = getattr(key, "name", key)
        assert py.builtin._istext(keyname) or py.builtin._isbytes(keyname)
        self._on_key_change.setdefault(keyname, []).append(subscriber)

    def wait_event_serial(self, serial):
        with threadlog.around("info", "waiting for event-serial %s", serial):
            with self.cv_new_event_serial:
                while serial >= self.read_event_serial():
                    self.cv_new_event_serial.wait()

    def wait_tx_serial(self, serial):
        with threadlog.around("info", "waiting for tx-serial %s", serial):
            with self.cv_new_transaction:
                while serial > self.keyfs.get_current_serial():
                    self.cv_new_transaction.wait()

    def read_event_serial(self):
        return read_int_from_file(self.event_serial_path, 0)

    def notify_on_commit(self, serial):
        with self.cv_new_transaction:
            self.cv_new_transaction.notify_all()

    def thread_shutdown(self):
        with self.cv_new_transaction:
            self.cv_new_transaction.notify_all()

    def thread_run(self):
        event_serial = self.read_event_serial()
        log = thread_push_log("[NOTI]")
        while 1:
            while event_serial < self.keyfs._fs.next_serial:
                self.thread.exit_if_shutdown()
                self._execute_hooks(event_serial, log)
                with self.cv_new_event_serial:
                    event_serial += 1
                    write_int_to_file(event_serial, self.event_serial_path)
                    self.cv_new_event_serial.notify_all()
            if event_serial >= self.keyfs._fs.next_serial:
                with self.cv_new_transaction:
                    self.cv_new_transaction.wait()
                    self.thread.exit_if_shutdown()

    def _execute_hooks(self, event_serial, log):
        log.debug("calling hooks for tx%s", event_serial)
        changes = self.keyfs._fs.get_changelog_entry(event_serial)
        for relpath, (keyname, back_serial, val) in changes.items():
            key = self.keyfs.derive_key(relpath, keyname)
            ev = KeyChangeEvent(key, val, event_serial, back_serial)
            subscribers = self._on_key_change.get(keyname, [])
            for sub in subscribers:
                log.debug("calling %s with key=%s, at_serial=%s, back_serial=%s",
                          sub, key, event_serial, back_serial)
                try:
                    sub(ev)
                except Exception:
                    log.exception("calling %s failed", sub)
                log.debug("finished %s", sub)
        log.debug("finished calling all hooks for tx%s", event_serial)


class KeyFS(object):
    """ singleton storage object. """
    def __init__(self, basedir):
        self.basedir = py.path.local(basedir).ensure(dir=1)
        self._keys = {}
        self._mode = None
        # a non-recursive lock because we don't support nested transactions
        self._write_lock = mythread.threading.Lock()
        self._threadlocal = mythread.threading.local()
        self._import_subscriber = {}
        self.notifier = t = TxNotificationThread(self)
        self._fs = Filesystem(self.basedir, notify_on_commit=t.notify_on_commit)

    def derive_key(self, relpath, keyname=None):
        """ return direct key for a given path and keyname.
        If keyname is not specified, the relpath key must exist
        to extract its name. """
        if keyname is None:
            try:
                return self.tx.get_key_in_transaction(relpath)
            except (AttributeError, KeyError):
                filepath = os.path.join(str(self.basedir), relpath)
                try:
                    keyname, last_serial = load_from_file(filepath)
                except IOError:
                    raise KeyError(relpath)
        key = self.get_key(keyname)
        if isinstance(key, PTypedKey):
            key = key(**key.extract_params(relpath))
        return key

    def import_changelog_entry(self, serial, entry):
        with self._write_lock:
            with self._fs.write_transaction() as fswriter:
                next_serial = self.get_next_serial()
                assert next_serial == serial, (next_serial, serial)
                for relpath, tup in entry.items():
                    name, back_serial, val = tup
                    typedkey = self.derive_key(relpath, name)
                    fswriter.record_set(typedkey, val)
                    meth = self._import_subscriber.get(typedkey.name)
                    if meth is not None:
                        meth(fswriter, typedkey, val, back_serial)

    def subscribe_on_import(self, key, subscriber):
        assert key.name not in self._import_subscriber
        self._import_subscriber[key.name] = subscriber

    def get_next_serial(self):
        return self._fs.next_serial

    def get_current_serial(self):
        return self.get_next_serial() - 1

    @property
    def tx(self):
        return getattr(self._threadlocal, "tx")

    def get_value_at(self, typedkey, at_serial):
        relpath = typedkey.relpath
        try:
            keyname, last_serial = load_from_file(typedkey.filepath)
        except IOError:
            raise KeyError(relpath)
        while last_serial >= 0:
            tup = self._fs.get_from_transaction_entry(last_serial, relpath)
            assert tup, "no transaction entry at %s" %(last_serial)
            keyname, back_serial, val = tup
            if last_serial > at_serial:
                last_serial = back_serial
                continue
            if val is not None:
                return copy_if_mutable(val)
            raise KeyError(relpath)  # was deleted

        # we could not find any change below at_serial which means
        # the key didn't exist at that point in time
        raise KeyError(relpath)

    def add_key(self, name, path, type):
        assert isinstance(path, py.builtin._basestring)
        if "{" in path:
            key = PTypedKey(self, path, type, name)
        else:
            key = TypedKey(self, path, type, name)
        self._keys[name] = key
        setattr(self, name, key)
        return key

    def get_key(self, name):
        return self._keys.get(name)

    def begin_transaction_in_thread(self, write=False, at_serial=None):
        assert not hasattr(self._threadlocal, "tx")
        tx = Transaction(self, write=write, at_serial=at_serial)
        self._threadlocal.tx = tx
        thread_push_log("[%stx%s]" %("W" if write else "R", tx.at_serial))
        return tx

    def clear_transaction(self):
        thread_pop_log()
        del self._threadlocal.tx

    def restart_as_write_transaction(self):
        tx = self.tx
        thread_pop_log()
        tx.restart(write=True)
        thread_push_log("[Wtx%s]" %(tx.at_serial))

    def restart_read_transaction(self):
        tx = self.tx
        assert not tx.write, "can only restart from read transaction"
        thread_pop_log()
        tx.restart(write=False)
        thread_push_log("[Rtx%s]" %(tx.at_serial))

    def rollback_transaction_in_thread(self):
        self._threadlocal.tx.rollback()
        self.clear_transaction()

    def commit_transaction_in_thread(self):
        self._threadlocal.tx.commit()
        self.clear_transaction()

    @contextlib.contextmanager
    def transaction(self, write=False, at_serial=None):
        tx = self.begin_transaction_in_thread(write=write, at_serial=at_serial)
        try:
            yield tx
        except:
            self.rollback_transaction_in_thread()
            raise
        self.commit_transaction_in_thread()


class PTypedKey:
    rex_braces = re.compile(r'\{(.+?)\}')
    def __init__(self, keyfs, key, type, name):
        self.keyfs = keyfs
        self.pattern = py.builtin._totext(key)
        self.type = type
        self.name = name
        def repl(match):
            name = match.group(1)
            return r'(?P<%s>[^\/]+)' % name
        rex_pattern = self.pattern.replace("+", r"\+")
        rex_pattern = self.rex_braces.sub(repl, rex_pattern)
        self.rex_reverse = re.compile("^" + rex_pattern + "$")

    def __call__(self, **kw):
        for val in kw.values():
            if "/" in val:
                raise ValueError(val)
        relpath = self.pattern.format(**kw)
        return TypedKey(self.keyfs, relpath, self.type, self.name,
                        params=kw)

    def extract_params(self, relpath):
        m = self.rex_reverse.match(relpath)
        return m.groupdict() if m is not None else {}

    def __repr__(self):
        return "<PTypedKey %r type %r>" %(self.pattern, self.type.__name__)


class KeyChangeEvent:
    def __init__(self, typedkey, value, at_serial, back_serial):
        self.typedkey = typedkey
        self.value = value
        self.at_serial = at_serial
        self.back_serial = back_serial


class TypedKey:
    def __init__(self, keyfs, relpath, type, name, params=None):
        self.keyfs = keyfs
        self.relpath = relpath
        self.type = type
        self.name = name
        self.filepath = os.path.join(str(keyfs.basedir), relpath)
        self.params = params or {}

    @cached_property
    def params(self):
        key = self.keyfs.get_key(self.name)
        if isinstance(key, PTypedKey):
            return key.extract_params(self.relpath)
        return {}

    def __hash__(self):
        return hash(self.relpath)

    def __eq__(self, other):
        return self.relpath == other.relpath

    def __repr__(self):
        return "<TypedKey %r type %r>" %(self.relpath, self.type.__name__)

    def get(self):
        return copy_if_mutable(self.keyfs.tx.get(self))

    @contextlib.contextmanager
    def update(self):
        val = self.keyfs.tx.get(self)
        yield val
        # no exception, so we can set and thus mark dirty the object
        self.set(val)

    def set(self, val):
        if not isinstance(val, self.type):
            raise TypeError("%r requires value of type %r, got %r" %(
                            self.relpath, self.type.__name__,
                            type(val).__name__))
        self.keyfs.tx.set(self, val)

    def exists(self):
        return self.keyfs.tx.exists(self)

    def delete(self):
        return self.keyfs.tx.delete(self)


class Transaction(object):
    commit_serial = None
    write = False

    def __init__(self, keyfs, at_serial=None, write=False):
        self.keyfs = keyfs
        if write:
            assert at_serial is None, "write trans cannot use at_serial"
            keyfs._write_lock.acquire()
            self.write = True
        if at_serial is None:
            at_serial = keyfs.get_next_serial() - 1
        self.at_serial = at_serial
        self.cache = {}
        self.dirty = set()
        self.dirty_files = {}

    def io_file_exists(self, path):
        try:
            return self.dirty_files[path] is not None
        except KeyError:
            return os.path.exists(path)

    def io_file_set(self, path, content):
        self.dirty_files[path] = content

    def io_file_get(self, path):
        try:
            content = self.dirty_files[path]
        except KeyError:
            with open(path, "rb") as f:
                return f.read()
        if content is None:
            raise IOError()
        return content

    def io_file_size(self, path):
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
        self.dirty_files[path] = None

    def exists_typed_state(self, typedkey):
        try:
            self.keyfs.get_value_at(typedkey, self.at_serial)
        except KeyError:
            return False
        return True

    def get_key_in_transaction(self, relpath):
        for key in self.cache:
            if key.relpath == relpath:
                return key
        raise KeyError(relpath)

    def get(self, typedkey):
        try:
            return copy_if_mutable(self.cache[typedkey])
        except KeyError:
            if typedkey in self.dirty:
                return typedkey.type()
            try:
                val = self.keyfs.get_value_at(typedkey, self.at_serial)
            except KeyError:
                return typedkey.type()
            self.cache[typedkey] = val
            return copy_if_mutable(val)

    def exists(self, typedkey):
        if typedkey in self.cache:
            return True
        if typedkey in self.dirty:
            return False
        return self.exists_typed_state(typedkey)

    def delete(self, typedkey):
        assert self.write, "not in write-transaction"
        self.cache.pop(typedkey, None)
        self.dirty.add(typedkey)

    def set(self, typedkey, val):
        assert self.write, "not in write-transaction"
        self.cache[typedkey] = val
        self.dirty.add(typedkey)

    def commit(self):
        if not self.write:
            return self._close()
        if not self.dirty and not self.dirty_files:
            threadlog.debug("nothing to commit, just closing tx")
            return self._close()
        try:
            with self.keyfs._fs.write_transaction() as fswriter:
                for typedkey in self.dirty:
                    val = self.cache.get(typedkey)
                    fswriter.record_set(typedkey, val)
                for path, content in self.dirty_files.items():
                    if content is None:
                        fswriter.record_rename_file(None, path)
                    else:
                        tmppath = path + "-tmp"
                        with get_write_file_ensure_dir(tmppath) as f:
                            f.write(content)
                        fswriter.record_rename_file(tmppath, path)
                commit_serial = fswriter.fs.next_serial
        finally:
            self._close()
        self.commit_serial = commit_serial
        return commit_serial

    def _close(self):
        del self.cache
        del self.dirty
        if self.write:
            self.keyfs._write_lock.release()
        return self.at_serial

    def rollback(self):
        threadlog.debug("transaction rollback at %s" % (self.at_serial))
        return self._close()

    def restart(self, write=False):
        self.commit()
        threadlog.debug("restarting afresh as write transaction")
        newtx = self.__class__(self.keyfs, write=write)
        self.__dict__ = newtx.__dict__


def copy_if_mutable(val, _immutable=(py.builtin.text, type(None), int, tuple,
                                     py.builtin.bytes, float)):
    if isinstance(val, _immutable):
        return val
    if isinstance(val, dict):
        return {k:copy_if_mutable(v) for k, v in val.items()}
    elif isinstance(val, list):
        return [copy_if_mutable(item) for item in val]
    elif isinstance(val, set):
        return set(copy_if_mutable(item) for item in val)
    raise ValueError("don't know how to handle type %r" % type(val))
