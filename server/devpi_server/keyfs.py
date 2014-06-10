"""
filesystem key/value storage with support for storing and retrieving
basic python types based on parametrizable keys.  Multiple
ReadTransactions can execute concurrently while at most one
WriteTransaction is ongoing.  Each ReadTransaction will see a consistent
view of key/values refering to the point in time it was started,
independent from any future changes.
"""
from __future__ import unicode_literals
import re
import contextlib
import py
import threading
import os
import sys

from execnet.gateway_base import Unserializer, _Serializer
from devpi_common.types import cached_property

import logging

log = logging.getLogger(__name__)
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
        f.write(str(val))
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
    def __init__(self, basedir, notify_on_transaction):
        self.basedir = basedir
        self._notify_on_transaction = notify_on_transaction
        self.path_next_serial = str(basedir.join(".nextserial"))
        self.path_changelogdir = basedir.ensure(".changelog", dir=1)
        self.next_serial = read_int_from_file(self.path_next_serial)
        self._changelog_cache = {}

    def write_transaction(self):
        return FSWriter(self)

    def get_from_transaction_entry(self, serial, relpath):
        return self.get_changelog_entry(serial).get(relpath)

    def get_raw_changelog_entry(self, serial):
        p = self.path_changelogdir.join(str(serial))
        with p.open("rb") as f:
            return f.read()

    def get_changelog_entry(self, serial):
        try:
            return self._changelog_cache[serial]
        except KeyError:
            p = self.path_changelogdir.join(str(serial))
            val = load_from_file(str(p))
            # XXX fix unboundedness of cache
            self._changelog_cache[serial] = val
            return val


class FSWriter:
    def __init__(self, fs):
        self.fs = fs
        self.pending_removes = []
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
        self.changes[relpath] = (typedkey.name, back_serial, value)
        self.pending_renames.append((tmp_path, target_path))

    def __enter__(self):
        return self

    def __exit__(self, cls, val, tb):
        if cls is None:
            self.commit_to_filesystem()
            commit_serial = self.fs.next_serial - 1
            log.info("tx%s committed", commit_serial)
            if self.changes:
                log.debug(" changed:%s" % ",".join(self.changes))
                self.fs._notify_on_transaction(commit_serial)
            return
        while self.pending_renames:
            source, dest = self.pending_renames.pop()
            os.remove(source)
        log.info("fstransaction roll back at %s" %(self.fs.next_serial))

    def commit_to_filesystem(self):
        # XXX assumption: we don't crash in the middle of this function
        p = self.fs.path_changelogdir.join(str(self.fs.next_serial))
        assert not p.exists(), (  # XXX recover
                    "change entry %s already exists, unclean shutdown?" %
                    self.fs.next_serial)
        self._direct_write(p, self.changes)

        # do all renames and then removes
        for source, dest in self.pending_renames:
            rename(source, dest)
        for dest in self.pending_removes:
            try:
                os.remove(dest)
            except py.error.ENOENT:
                pass

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


class TxNotificationThread(threading.Thread):
    def __init__(self, keyfs):
        threading.Thread.__init__(self)
        self.setDaemon(True)
        self.keyfs = keyfs
        self.new_transaction = threading.Event()
        self.event_serial_path = str(self.keyfs.basedir.join(".event_serial"))
        self.running = True

    def read_event_serial(self):
        return read_int_from_file(self.event_serial_path, 0)

    def write_event_serial(self, serial):
        write_int_to_file(serial, self.event_serial_path)

    def notify_on_transaction(self, serial):
        self.new_transaction.set()

    def shutdown(self):
        self.running = False
        self.new_transaction.set()

    def run(self):
        while 1:
            event_serial = self.read_event_serial()
            if event_serial >= self.keyfs._fs.next_serial:
                self.new_transaction.wait()
                self.new_transaction.clear()
            if not self.running:
                break
            while event_serial < self.keyfs._fs.next_serial:
                self.execute_hooks(event_serial)
                event_serial += 1
                self.write_event_serial(event_serial)

    def execute_hooks(self, event_serial):
        log.debug("calling key hooks for tx%s", event_serial)
        changes = self.keyfs._fs.get_changelog_entry(event_serial)
        for relpath, (keyname, back_serial, val) in changes.items():
            key = self.keyfs.derive_key(relpath, keyname)
            ev = KeyChangeEvent(key, val, event_serial, back_serial)
            for sub in key._subscribers:
                log.debug("calling %s", sub)
                try:
                    sub(ev)
                except Exception:
                    log.exception("calling %s failed", sub)


class KeyFS(object):
    """ singleton storage object. """
    def __init__(self, basedir):
        self.basedir = py.path.local(basedir).ensure(dir=1)
        self._keys = {}
        self._mode = None
        # a non-recursive lock because we don't support nested transactions
        self._write_lock = threading.Lock()
        self._threadlocal = threading.local()
        self._notifier = t = TxNotificationThread(self)
        self._fs = Filesystem(self.basedir,
                              notify_on_transaction=t.notify_on_transaction)

    def start_notifier(self):
        self._notifier.start()

    def shutdown(self):
        self._notifier.shutdown()

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

    def get_next_serial(self):
        return self._fs.next_serial

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
                return val
            raise KeyError(relpath)  # was deleted

        # we could not find any change below at_serial which means
        # the key didn't exist at that point in time
        raise KeyError(relpath)

    def mkdtemp(self, prefix):
        # XXX only used from devpi-web, could be managed there
        tmpdir = self.basedir.ensure(".tmp", dir=1)
        return py.path.local.make_numbered_dir(prefix=prefix, rootdir=tmpdir)

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

    def begin_transaction_in_thread(self, write=False):
        assert not hasattr(self._threadlocal, "tx")
        tx = WriteTransaction(self) if write else ReadTransaction(self)
        self._threadlocal.tx = tx
        return tx

    def clear_transaction(self):
        del self._threadlocal.tx

    def restart_as_write_transaction(self):
        self.commit_transaction_in_thread()
        self.begin_transaction_in_thread(write=True)

    def rollback_transaction_in_thread(self):
        self._threadlocal.tx.rollback()
        self.clear_transaction()

    def commit_transaction_in_thread(self):
        self._threadlocal.tx.commit()
        self.clear_transaction()

    @contextlib.contextmanager
    def transaction(self, write=True):
        self.begin_transaction_in_thread(write=write)
        try:
            yield
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
        self._subscribers = []
        def repl(match):
            name = match.group(1)
            return r'(?P<%s>[^\/]+)' % name
        rex_pattern = self.pattern.replace("+", r"\+")
        rex_pattern = self.rex_braces.sub(repl, rex_pattern)
        self.rex_reverse = re.compile("^" + rex_pattern + "$")

    def register_subscriber(self, func):
        self._subscribers.append(func)

    def __call__(self, **kw):
        for val in kw.values():
            if "/" in val:
                raise ValueError(val)
        relpath = self.pattern.format(**kw)
        return TypedKey(self.keyfs, relpath, self.type, self.name,
                        frompattern=(self._subscribers, kw))

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
    def __init__(self, keyfs, relpath, type, name, frompattern=None):
        self.keyfs = keyfs
        self.relpath = relpath
        self.type = type
        self.name = name
        self.filepath = os.path.join(str(keyfs.basedir), relpath)
        if frompattern is None:
            self._subscribers = []
        else:
            self._subscribers, self.params = frompattern

    @cached_property
    def params(self):
        key = self.keyfs.get_key(self.name)
        if isinstance(key, PTypedKey):
            return key.extract_params(self.relpath)
        return {}

    def register_subscriber(self, func):
        log.debug("registering subscriber %s", func)
        self._subscribers.append(func)

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


class ReadTransaction(object):
    def __init__(self, keyfs):
        self.keyfs = keyfs
        self.at_serial = keyfs.get_next_serial() - 1
        self.cache = {}
        self.dirty = set()

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
            return self.cache[typedkey]
        except KeyError:
            if typedkey in self.dirty:
                return typedkey.type()
            try:
                val = self.keyfs.get_value_at(typedkey, self.at_serial)
            except KeyError:
                return typedkey.type()
            self.cache[typedkey] = copy_if_mutable(val)
            return val

    def exists(self, typedkey):
        if typedkey in self.cache:
            return True
        if typedkey in self.dirty:
            return False
        return self.exists_typed_state(typedkey)

    def _close(self):
        del self.cache
        del self.dirty
        return self.at_serial

    commit = rollback = _close


class WriteTransaction(ReadTransaction):
    def __init__(self, keyfs):
        keyfs._write_lock.acquire()
        super(WriteTransaction, self).__init__(keyfs)

    def delete(self, typedkey):
        self.cache.pop(typedkey, None)
        self.dirty.add(typedkey)

    def set(self, typedkey, val):
        self.cache[typedkey] = val
        self.dirty.add(typedkey)

    def commit(self):
        if not self.dirty:
            return self._close()
        try:
            with self.keyfs._fs.write_transaction() as fswriter:
                for typedkey in self.dirty:
                    try:
                        val = self.cache[typedkey]
                    except KeyError:
                        val = None
                    fswriter.record_set(typedkey, val)
                at_serial = fswriter.fs.next_serial
        finally:
            self._close()
        return at_serial

    def _close(self):
        serial = super(WriteTransaction, self)._close()
        self.keyfs._write_lock.release()
        return serial

    def rollback(self):
        log.debug("transaction rollback at %s" % (self.at_serial))
        return self._close()


def copy_if_mutable(val):
    if isinstance(val, dict):
        return val.copy()
    elif isinstance(val, list):
        return list(val)
    return val
