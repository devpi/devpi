"""
filesystem key/value storage with support for storing and retrieving
basic python types based on parametrizable keys.  Multiple
ReadTransactions can execute concurrently while at most one
WriteTransaction is ongoing.  Each ReadTransaction will see a consistent
view of key/values refering to the point in time it was started,
independent from any future changes.
"""
from __future__ import unicode_literals
import contextlib
import py
import threading
import os
import sys
from execnet import load, dump

import logging

log = logging.getLogger(__name__)
_nodefault = object()


class Serializer:
    def __init__(self, stream):
        from execnet.gateway_base import _Serializer
        self.stream = _Serializer(write=stream.write)

    def save(self, obj):
        self.stream.save(obj, versioned=False)

class Unserializer:
    def __init__(self, stream):
        from execnet.gateway_base import Unserializer
        self.stream = Unserializer(stream, (False, False))

    def load(self):
        return self.stream.load(versioned=False)


class Filesystem:
    def __init__(self, basedir):
        self.basedir = basedir
        self.path_current_serial = basedir.join(".currentserial")
        self.path_changelogdir = basedir.ensure(".changelog", dir=1)
        try:
            self.current_serial = self._read(self.path_current_serial)
        except py.error.Error:
            self.current_serial = 0
       
    def _read(self, path):
        with path.open("rb") as f:
            return load(f)

    def write_transaction(self):
        return FSWriter(self)

    def get_transaction_entry(self, serial):
        p = self.path_changelogdir.join(str(serial))
        return self._read(p)


class FSWriter:
    def __init__(self, fs):
        self.fs = fs
        self.pending_removes = []
        self.pending_renames = []
        self.record_deleted = []
        self.record_set = []

    def direct_write(self, path, val):
        tmpfile = path + "-tmp"
        with tmpfile.open("wb") as f:
            dump(f, val)
        tmpfile.rename(path)

    def set_mutable(self, relpath, value=_nodefault):
        target_path = self.fs.basedir.join(relpath)
        tmp_path = target_path + ".tmp"
        # read history serials
        current_serial = self.fs.current_serial
        try:
            with target_path.open("rb") as f:
                history_serials = [current_serial] + Unserializer(f).load()
        except py.error.Error:
            history_serials = [current_serial]
            tmp_path.dirpath().ensure(dir=1)
        with tmp_path.open("wb") as f:
            serializer = Serializer(f)
            serializer.save(history_serials)
            if value is not _nodefault: 
                serializer.save(value)
                self.record_set.append((relpath, value))
            else:
                self.record_deleted.append(relpath)
        self.pending_renames.append((tmp_path.strpath, target_path.strpath))

    def set(self, relpath, value):
        target_path = self.fs.basedir.join(relpath)
        tmp_path = target_path + ".tmp"
        tmp_path.write(value, mode="wb", ensure=True)
        self.pending_renames.append((tmp_path.strpath, target_path.strpath))
        self.record_set.append((relpath, value))

    def delete(self, relpath):
        self.pending_removes.append(self.fs.basedir.join(relpath).strpath)
        self.record_deleted.append(relpath)

    def __enter__(self):
        return self

    def __exit__(self, cls, val, tb):
        if cls is None:
            changed = [x[0] for x in self.record_set]
            self.commit()
            log.info("fstransaction committed " + str(self.fs.current_serial-1))
            if changed:
                log.debug(" changed:%s" % ",".join(changed))
            if self.record_deleted:
                log.debug(" deleted:%s" % ",".join(self.record_deleted))
        else:
            while self.pending_renames:
                source, dest = self.pending_renames.pop()
                os.remove(source)
            log.info("fstransaction roll back at %s" %(self.fs.current_serial))

    def commit(self):
        # XXX assumption: we don't crash in the middle of this function
        # write out changelog entry
        p = self.fs.path_changelogdir.join(str(self.fs.current_serial))
        assert not p.exists(), (  # XXX recover
                    "change entry already exists, unclean shutdown?")
        entry = dict(record_deleted=self.record_deleted, 
                     record_set=self.record_set)
        self.direct_write(p, entry)

        # do all renames and then removes
        for source, dest in self.pending_renames:
            rename(source, dest)
        for dest in self.pending_removes:
            try:
                os.remove(dest)
            except py.error.ENOENT:
                pass

        # finally increment the serial and write it out
        self.fs.current_serial += 1
        self.direct_write(self.fs.path_current_serial, self.fs.current_serial)


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


class KeyFS(object):
    """ singleton storage object. """
    def __init__(self, basedir):
        self.basedir = py.path.local(basedir).ensure(dir=1)
        self._keys = {}
        self._mode = None
        # a non-recursive lock because we don't support nested transactions
        self._write_lock = threading.Lock()
        self._threadlocal = threading.local()
        self._fs = Filesystem(self.basedir)

    @property
    def tx(self):
        return getattr(self._threadlocal, "tx")

    def _get(self, relpath):
        try:
            with self._getpath(relpath).open("rb") as f:
                return f.read()
        except py.error.Error:
            raise KeyError(relpath)

    def mkdtemp(self, prefix):
        # XXX only used from devpi-web, could be managed there
        tmpdir = self.basedir.ensure(".tmp", dir=1)
        return py.path.local.make_numbered_dir(prefix=prefix, rootdir=tmpdir)

    def _get_mutable(self, relpath, target_serial):
        try:
            f = self._getpath(relpath).open("rb")
        except py.error.Error:
            raise KeyError(relpath)
        with f:
            unserializer = Unserializer(f)
            history_serials = unserializer.load()
            if history_serials.pop(0) < target_serial:
                # latest state is older already than what we require
                try:
                    return unserializer.load()
                except EOFError:  # a delete entry
                    raise KeyError(relpath)
           
        for serial in history_serials:
            if serial < target_serial:
                # we found the latest state fit for what we require
                change_entry = self._fs.get_transaction_entry(serial)
                if relpath in change_entry["record_deleted"]:
                    raise KeyError(relpath)
                for rp, val in change_entry["record_set"]:
                    if rp == relpath:
                        return val

        # we could not find any historic serial lower than target_serial
        # which means the key didn't exist
        raise KeyError(relpath)

    def _exists(self, relpath):
        return self._getpath(relpath).check()

    def _getpath(self, relpath):
        assert isinstance(relpath, py.builtin._basestring), \
               (type(relpath), relpath)
        return self.basedir.join(relpath)

    def addkey(self, key, type, name=None):
        assert isinstance(key, py.builtin._basestring)
        if "{" in key:
            key = PTypedKey(self, key, type)
        else:
            key = TypedKey(self, key, type)
        if name is not None:
            self._keys[name] = key
            setattr(self, name, key)
        return key

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
    def __init__(self, keyfs, key, type):
        self.keyfs = keyfs
        self.key = py.builtin._totext(key)
        self.type = type

    def __call__(self, **kw):
        realkey = self.key.format(**kw)
        return TypedKey(self.keyfs, realkey, self.type)

    def __repr__(self):
        return "<PTypedKey %r type %r>" %(self.key, self.type.__name__)


class TypedKey:
    def __init__(self, keyfs, relpath, type):
        self.keyfs = keyfs
        self.relpath = relpath
        self.type = type

    def __hash__(self):
        return hash(self.relpath)

    def __eq__(self, other):
        return self.relpath == other.relpath

    @property
    def filepath(self):
        return self.keyfs._getpath(self.relpath)

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
        self.from_serial = keyfs._fs.current_serial
        self.cache = {}
        self.dirty = set()

    def get_typed_state(self, typedkey):
        if typedkey.type == bytes:
            return self.keyfs._get(typedkey.relpath)
        val = self.keyfs._get_mutable(typedkey.relpath, self.from_serial)
        assert isinstance(val, typedkey.type), val
        return val

    def exists_typed_state(self, typedkey):
        try:
            self.get_typed_state(typedkey)
        except KeyError:
            return False
        return True

    def get(self, typedkey):
        try:
            return self.cache[typedkey]
        except KeyError:
            if typedkey in self.dirty:
                return typedkey.type()
            try:
                val = self.get_typed_state(typedkey)
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
        return self.from_serial - 1

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
                    relpath = typedkey.relpath
                    try:
                        val = self.cache[typedkey]
                    except KeyError:
                        if typedkey.type == bytes:
                            fswriter.delete(relpath)
                        else:
                            fswriter.set_mutable(relpath)
                    else:
                        if typedkey.type == bytes:
                            fswriter.set(relpath, val)
                        else:
                            fswriter.set_mutable(relpath, val)
                current_serial = fswriter.fs.current_serial
        finally:
            self._close()
        return current_serial

    def _close(self):
        serial = super(WriteTransaction, self)._close()
        self.keyfs._write_lock.release()
        return serial

    def rollback(self):
        log.debug("transaction rollback at %s" % (self.from_serial - 1))
        return self._close()
        

def copy_if_mutable(val):
    if isinstance(val, dict):
        return val.copy()
    elif isinstance(val, list):
        return list(val)
    return val
