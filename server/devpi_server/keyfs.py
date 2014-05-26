"""

filesystem key/value storage with support for
storing basic python types.

With thread-safe transaction support in the following manner.


"""
from __future__ import unicode_literals
import contextlib
import py
import threading
from tempfile import NamedTemporaryFile
import os
import sys
from os.path import basename, isabs, join
from execnet import dumps, loads

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


class KeyFS(object):
    def __init__(self, basedir):
        self.basedir = py.path.local(basedir).ensure(dir=1)
        self.keys = []
        self._locks = {}
        self._mode = None
        # a non-recursive lock because we don't support nested transactions
        self.write_lock = threading.Lock()
        self._threadlocal = threading.local()
        self.CURRENT_SERIAL = get_typed_key(self, ".currentserial", int)
        self.SERIALS = PTypedKey(self, ".serials/{serial}", dict)
        try:
            dumped_serial = self._get(self.CURRENT_SERIAL.relpath)
        except KeyError:
            self.current_serial = 0
        else:
            self.current_serial = loads(dumped_serial)

    @property
    def tx(self):
        try:
            return self._threadlocal.tx
        except AttributeError:
            return RootState(self)

    @cached_property
    def tmpdir(self):
        return str(self.basedir.ensure(".tmp", dir=1))

    def _get(self, relpath):
        try:
            with self._getpath(relpath).open("rb") as f:
                return f.read()
        except py.error.Error:
            raise KeyError(relpath)

    def chmod(self, file_name):
        if self._mode is None:
            umask = os.umask(0)
            os.umask(umask)
            self._mode = 0o666 ^ umask
        os.chmod(file_name, self._mode)

    def tempfile(self, prefix="tmp"):
        f = NamedTemporaryFile(prefix=prefix, dir=self.tmpdir, delete=False)
        relpath = os.path.relpath(f.name, str(self.basedir))
        # change from hardcoded default perm 0600 in tempfile._mkstemp_inner()
        self.chmod(f.name)
        f.key = get_typed_key(self, relpath, bytes)
        return f

    def mkdtemp(self, prefix):
        return py.path.local.make_numbered_dir(
                    prefix=prefix, rootdir=py.path.local(self.tmpdir))

    def _set_mutable(self, relpath, serial, value=_nodefault):
        try:
            with self._getpath(relpath).open("rb") as f:
                history_serials = [serial] + Unserializer(f).load()
        except py.error.Error:
            history_serials = [serial]
        with self.tempfile(basename(relpath)) as f:
            serializer = Serializer(f)
            serializer.save(history_serials)
            if value is not _nodefault: 
                serializer.save(value)
        self._rename(f.key.relpath, relpath)

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
                key = self.SERIALS(serial=serial)
                key_relpath = key.relpath
                change_entry = loads(self._get(key_relpath))
                if relpath in change_entry["record_deleted"]:
                    raise KeyError(relpath)
                for rp, val in change_entry["record_set"]:
                    if rp == relpath:
                        return val

        # we could not find any historic serial lower than target_serial
        # which means the key didn't exist
        raise KeyError(relpath)

    def _set(self, relpath, value):
        with self.tempfile(basename(relpath)) as f:
            f.write(value)
        self._rename(f.key.relpath, relpath)
        return True

    def _rename(self, rel_source, rel_dest):
        assert not isabs(rel_source), rel_source
        assert not isabs(rel_dest), rel_dest
        source = join(str(self.basedir), rel_source)
        dest = join(str(self.basedir), rel_dest)
        try:
            os.rename(source, dest)
        except OSError:
            destdir = os.path.dirname(dest)
            if not os.path.exists(destdir):
                os.makedirs(destdir)
            if sys.platform == "win32" and os.path.exists(dest):
                os.remove(dest)
            os.rename(source, dest)

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

    def addkey(self, key, type):
        assert isinstance(key, py.builtin._basestring)
        if "{" in key:
            key = PTypedKey(self, key, type)
        else:
            key = get_typed_key(self, key, type)
        self.keys.append(key)
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

    def commit_changes(self, from_serial, record_set, record_deleted, nohist):
        # this is the only place that ever writes changes 
        # to the filesystem.  We play it safe and simple and 
        # completely serialize all writes.
        with self.write_lock:
            #print "starting transaction", self
            #print "  record_set", record_set
            #print "  record_deleted", record_deleted
            #print "  record_immutable", record_immutable
            #print "  record_immutable_deleted", record_immutable_deleted
            # we get our current serial number for changes
            serial = self.current_serial
            key = self.SERIALS(serial=serial)
            assert not self._exists(key.relpath), (  # XXX recover
                    "change entry already exists, unclean shutdown?")

            # first write out the complete change entry for our serial
            d = dict(record_set=record_set, record_deleted=record_deleted)
            self._set(key.relpath, dumps(d))

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

            # finally increment the current serial and write it out
            # thus completing the transaction
            self.current_serial += 1
            self._set(self.CURRENT_SERIAL.relpath, dumps(self.current_serial))
            # XXX we need to fsync for the D in ACID
            log.info("transaction committed %s" %(serial,))


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

    def move(self, destkey):
        if self.type != destkey.type:
            raise TypeError("key %r has type %r, destkey %r has type %r" % (
                            self.relpath, self.type.__name__,
                            destkey.relpath, destkey.type.__name__))
        assert self.type == bytes
        self.keyfs.tx.move(self, destkey)


class RootState:
    def __init__(self, keyfs):
        self.keyfs = keyfs

    def exists(self, typedkey):
        with self.keyfs.transaction():
            return typedkey.exists()

    def get(self, typedkey):
        with self.keyfs.transaction():
            return typedkey.get()


class Transaction:
    def __init__(self, keyfs):
        self.keyfs = keyfs
        self.from_serial = keyfs.current_serial
        self.cache = {}
        self.dirty = set()
        self.rootstate = keyfs.tx
        assert isinstance(self.rootstate, RootState), (
                    "nested transactions not supported")

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

    def move(self, sourcekey, destkey):
        val = self.get(sourcekey)
        if destkey.type == bytes:
            assert not destkey.exists()
        self.set(destkey, val)
        self.delete(sourcekey)

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
            from_serial=self.from_serial,
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

