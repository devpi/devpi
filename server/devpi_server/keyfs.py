"""

filesystem key/value storage with support for
storing basic python types.

With thread-safe transaction support in the following manner.


"""
from __future__ import unicode_literals
import contextlib
import py
import threading
import os
import sys
from os.path import basename, isabs, join
from execnet import dumps, loads, load, dump

from devpi_common.types import cached_property
import logging

log = logging.getLogger(__name__)
_nodefault = object()
HIST = 2
NOHIST = 3


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
        self._path_current_serial = basedir.join(".currentserial")
        self._path_changelogdir = basedir.ensure(".changelog", dir=1)
        try:
            self.current_serial = self._read(self._path_current_serial)
        except py.error.Error:
            self.current_serial = 0
       
    def _read(self, path):
        with path.open("rb") as f:
            return load(f)

    def _write(self, path, val):
        tmpfile = path + "-tmp"
        with tmpfile.open("wb") as f:
            dump(f, val)
        tmpfile.rename(path)

    @contextlib.contextmanager
    def write_transaction(self, entry):
        # first write out the complete change entry for our serial
        p = self._path_changelogdir.join(str(self.current_serial))
        assert not p.exists(), (  # XXX recover
                    "change entry already exists, unclean shutdown?")
        self._write(p, entry)
        yield self.current_serial
        self.current_serial += 1
        self._write(self._path_current_serial, self.current_serial)
        log.info("transaction committed %s" %(self.current_serial-1))

    def get_transaction_entry(self, serial):
        p = self._path_changelogdir.join(str(serial))
        return self._read(p)


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
        self.write_lock = threading.Lock()
        self._threadlocal = threading.local()
        self._fs = Filesystem(self.basedir)

    @property
    def tx(self):
        try:
            return self._threadlocal.tx
        except AttributeError:
            return self

    def _get(self, relpath):
        try:
            with self._getpath(relpath).open("rb") as f:
                return f.read()
        except py.error.Error:
            raise KeyError(relpath)

    @contextlib.contextmanager
    def _writing(self, relpath):
        target_path = self.basedir.join(relpath)
        tmp_path = target_path.dirpath("." + target_path.basename + ".tmp")
        try:
            f = tmp_path.open("wb")
        except py.error.ENOENT:
            target_path.dirpath().ensure(dir=1)
            f = tmp_path.open("wb")
        try:
            with f:
                yield f
        except Exception:
            tmp_path.remove()
            raise
        rename(f.name, target_path.strpath)

    def mkdtemp(self, prefix):
        # XXX only used from devpi-web, could be managed there
        tmpdir = self.basedir.ensure(".tmp", dir=1)
        return py.path.local.make_numbered_dir(prefix=prefix, rootdir=tmpdir)

    def _set_mutable(self, relpath, serial, value=_nodefault):
        try:
            with self._getpath(relpath).open("rb") as f:
                history_serials = [serial] + Unserializer(f).load()
        except py.error.Error:
            history_serials = [serial]
        with self._writing(relpath) as f:
            serializer = Serializer(f)
            serializer.save(history_serials)
            if value is not _nodefault: 
                serializer.save(value)

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

    def _set(self, relpath, value):
        with self._writing(relpath) as f:
            f.write(value)
        return True

    def _exists(self, relpath):
        return self._getpath(relpath).check()

    def _delete(self, relpath):
        try:
            self._getpath(relpath).remove()
        except py.error.ENOENT:  # XXX can this happen?
            return False
        return True

    def _getpath(self, relpath):
        assert isinstance(relpath, py.builtin._basestring), \
               (type(relpath), relpath)
        return self.basedir.join(relpath)

    def destroyall(self):
        if self.basedir.check():
            self.basedir.remove()

    def addkey(self, key, type, name=None):
        assert isinstance(key, py.builtin._basestring)
        if "{" in key:
            key = PTypedKey(self, key, type)
        else:
            key = get_typed_key(self, key, type)
        if name is not None:
            self._keys[name] = key
            setattr(self, name, key)
        return key

    @contextlib.contextmanager
    def transaction(self):
        self._threadlocal.tx = tx = Transaction(self)
        try:
            try:
                yield
            except:
                tx.rollback()
                raise
            tx.commit()
        finally:
            del self._threadlocal.tx

    def commit_changes(self, record_set, record_deleted, nohist):
        # this is the only place that ever writes changes 
        # to the filesystem.  We play it safe and simple and 
        # completely serialize all writes.
        with self.write_lock:
            #print "starting transaction", self
            #print "  record_set", record_set
            #print "  record_deleted", record_deleted
            # we get our current serial number for changes
            entry = dict(record_set=record_set, record_deleted=record_deleted)
            with self._fs.write_transaction(entry) as serial:
                # then perform the actual key/val changes on the file system
                for relpath in record_deleted:
                    if relpath in nohist:
                        self._delete(relpath)
                    else:
                        self._set_mutable(relpath, serial)
                for relpath, val in record_set:
                    if relpath in nohist:
                        self._set(relpath, val)
                    else:
                        self._set_mutable(relpath, serial, val)

    def exists(self, typedkey):
        with self.transaction():
            return typedkey.exists()

    def get(self, typedkey):
        with self.transaction():
            return typedkey.get()


class PTypedKey:
    def __init__(self, keyfs, key, type):
        self.keyfs = keyfs
        self.key = py.builtin._totext(key)
        self.type = type

    def __call__(self, **kw):
        realkey = self.key.format(**kw)
        return get_typed_key(self.keyfs, realkey, self.type)

    def __repr__(self):
        return "<PTypedKey %r type %r>" %(self.key, self.type.__name__)

def get_typed_key(keyfs, relpath, type):
    if type == "DIR":
        return DirKey(keyfs, relpath)
    return TypedKey(keyfs, relpath, type)

class DirKey:
    def __init__(self, keyfs, relpath):
        self.keyfs = keyfs
        self.relpath = relpath
        self.filepath = self.keyfs._getpath(self.relpath)

    def exists(self):
        return self.filepath.check()

    def delete(self):
        return self.filepath.remove()

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

    def verify_type(self, val):
        if not isinstance(val, self.type):
            raise TypeError("%r requires value of type %r, got %r" %(
                            self.relpath, self.type.__name__,
                            type(val).__name__))

    def get(self):
        return copy_if_mutable(self.keyfs.tx.get(self))

    @contextlib.contextmanager
    def update(self):
        val = self.keyfs.tx.get(self)
        yield val
        # no exception, so we can set and thus mark dirty the object
        self.set(val)

    def set(self, val):
        self.verify_type(val)
        self.keyfs.tx.set(self, val)

    def exists(self):
        return self.keyfs.tx.exists(self)

    def delete(self):
        return self.keyfs.tx.delete(self)



class Transaction:
    def __init__(self, keyfs):
        self.keyfs = keyfs
        self.from_serial = keyfs._fs.current_serial
        self.cache = {}
        self.dirty = set()
        self.rootstate = keyfs.tx
        assert self.rootstate == keyfs, "nested transactions not supported"

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

    def set(self, typedkey, val):
        self.cache[typedkey] = val
        self.dirty.add(typedkey)

    def exists(self, typedkey):
        if typedkey in self.cache:
            return True
        if typedkey in self.dirty:
            return False
        return self.exists_typed_state(typedkey)

    def delete(self, typedkey):
        self.cache.pop(typedkey, None)
        self.dirty.add(typedkey)

    def commit(self):
        if not self.dirty:
            return self._close()
        record_deleted = set()
        record_set = []
        nohist = set()
        for typedkey in self.dirty:
            relpath = typedkey.relpath
            if typedkey.type == bytes:
                nohist.add(relpath)
            try:
                val = self.cache[typedkey]
            except KeyError:
                record_deleted.add(relpath)
            else:
                record_set.append((relpath, val))
        new_serial = self.keyfs.commit_changes(
            record_set=record_set, record_deleted=record_deleted,
            nohist=nohist
        )
        self._close()
        return new_serial

    def _close(self):
        del self.cache
        del self.dirty

    def rollback(self):
        print("rolling back transaction" % self)
        self._close()
        

def copy_if_mutable(val):
    if isinstance(val, dict):
        return val.copy()
    elif isinstance(val, list):
        return list(val)
    return val

