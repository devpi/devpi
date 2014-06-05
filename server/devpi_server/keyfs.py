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

import logging

log = logging.getLogger(__name__)
_nodefault = object()

def load(io):
    return Unserializer(io, strconfig=(False, False)).load(versioned=False)

def dump(obj, io):
    return _Serializer(io.write).save(obj)


class Filesystem:
    def __init__(self, basedir):
        self.basedir = basedir
        self.path_next_serial = basedir.join(".nextserial")
        self.path_changelogdir = basedir.ensure(".changelog", dir=1)
        try:
            self.next_serial = self._read(self.path_next_serial)
        except py.error.Error:
            self.next_serial = 0

    def _read(self, path):
        with path.open("rb") as f:
            return load(f)

    def write_transaction(self):
        return FSWriter(self)

    def get_from_transaction_entry(self, serial, relpath):
        p = self.path_changelogdir.join(str(serial))
        change_entry = self._read(p)
        tup = change_entry.get(relpath)
        if tup is not None:
            try:
                keyname, val = tup
            except ValueError:  # only one value
                raise KeyError(relpath)
            return val

    def get_raw_changelog_entry(self, serial):
        p = self.path_changelogdir.join(str(serial))
        with p.open("rb") as f:
            return f.read()


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

    def record_set(self, typedkey, value=_nodefault):
        relpath = typedkey.relpath
        target_path = self.fs.basedir.join(relpath)
        tmp_path = target_path + ".tmp"
        # read history serials
        next_serial = self.fs.next_serial
        try:
            with target_path.open("rb") as f:
                history_serials = [next_serial] + load(f)
                # we record a maximum of the last three changing serials
                del history_serials[3:]
        except py.error.Error:
            history_serials = [next_serial]
            tmp_path.dirpath().ensure(dir=1)
        with tmp_path.open("wb") as f:
            dump(history_serials, f)
            if value is not _nodefault:
                dump(value, f)
                self.changes[relpath] = (typedkey.name, value)
            else:
                self.changes[relpath] = (typedkey.name,)
        self.pending_renames.append((tmp_path.strpath, target_path.strpath))

    def record_delete(self, typedkey):
        self.record_set(typedkey)

    def __enter__(self):
        return self

    def __exit__(self, cls, val, tb):
        if cls is None:
            changed = list(self.changes)
            self.commit_to_filesystem()
            log.info("fstransaction committed " + str(self.fs.next_serial-1))
            if changed:
                log.debug(" changed:%s" % ",".join(changed))
        else:
            while self.pending_renames:
                source, dest = self.pending_renames.pop()
                os.remove(source)
            log.info("fstransaction roll back at %s" %(self.fs.next_serial))

    def commit_to_filesystem(self):
        # XXX assumption: we don't crash in the middle of this function
        # write out changelog entry
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
        self._direct_write(self.fs.path_next_serial, self.fs.next_serial)


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

    def derive_typed_key(self, name, relpath):
        key = self.get_key(name)
        # XXX avoid parse out and parse back
        if isinstance(key, PTypedKey):
            key = key(**key.match_params(relpath))
        return key

    def import_changelog_entry(self, serial, entry):
        with self._write_lock:
            with self._fs.write_transaction() as fswriter:
                next_serial = self.get_next_serial()
                assert next_serial == serial, (next_serial, serial)
                for relpath, tup in entry.items():
                    name = tup[0]
                    typedkey = self.derive_typed_key(name, relpath)
                    try:
                        val = tup[1]
                    except IndexError:
                        fswriter.record_delete(typedkey)
                    else:
                        fswriter.record_set(typedkey, val)

    def get_next_serial(self):
        return self._fs.next_serial

    @property
    def tx(self):
        return getattr(self._threadlocal, "tx")

    def get_value_at(self, typedkey, at_serial):
        relpath = typedkey.relpath
        try:
            f = self._getpath(relpath).open("rb")
        except py.error.Error:
            raise KeyError(relpath)
        with f:
            history_serials = load(f)
            if history_serials.pop(0) <= at_serial:
                # latest state is older already than what we require
                try:
                    return load(f)
                except EOFError:  # a delete entry
                    raise KeyError(relpath)

        for serial in history_serials:
            if serial <= at_serial:
                # we found the latest state fit for what we require
                val = self._fs.get_from_transaction_entry(serial, relpath)
                if val is not _nodefault:
                    return val

        log.warn("performing exhaustive search on %s, %s", relpath, at_serial)
        # the history_serials are all newer than what we need
        # let's do an exhaustive search for the last change
        while at_serial > 0:
            val = self._fs.get_from_transaction_entry(at_serial, relpath)
            if val is not _nodefault:
                return val
            at_serial -= 1

        # we could not find any historic serial lower than target_serial
        # which means the key didn't exist at that point in time
        raise KeyError(relpath)

    def mkdtemp(self, prefix):
        # XXX only used from devpi-web, could be managed there
        tmpdir = self.basedir.ensure(".tmp", dir=1)
        return py.path.local.make_numbered_dir(prefix=prefix, rootdir=tmpdir)

    def _exists(self, relpath):
        return self._getpath(relpath).check()

    def _getpath(self, relpath):
        assert isinstance(relpath, py.builtin._basestring), \
               (type(relpath), relpath)
        return self.basedir.join(relpath)

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
        self.slash = "*}" in self.pattern
        def repl(match):
            name = match.group(1)
            if name[-1] == "*":
                return r'(?P<%s>.+)' % name[:-1]
            return r'(?P<%s>[^\/]+)' % name
        rex_pattern = self.pattern.replace("+", r"\+")
        rex_pattern = self.rex_braces.sub(repl, rex_pattern)
        self.rex_reverse = re.compile("^" + rex_pattern + "$")

    def __call__(self, **kw):
        if not self.slash:
            for val in kw.values():
                if "/" in val:
                    raise ValueError(val)
            relpath = self.pattern.format(**kw)
        else:
            def repl(match):
                name = match.group(1)
                if name[-1] == "*":
                    val = kw[name[:-1]]
                else:
                    val = kw[name]
                    if "/" in val:
                        raise ValueError(val)
                return val
            relpath = self.rex_braces.sub(repl, self.pattern)
        return TypedKey(self.keyfs, relpath, self.type, self.name)

    def match_params(self, relpath):
        m = self.rex_reverse.match(relpath)
        if m is not None:
            return m.groupdict()
        return {}

    def __repr__(self):
        return "<PTypedKey %r type %r>" %(self.pattern, self.type.__name__)


class TypedKey:
    def __init__(self, keyfs, relpath, type, name):
        self.keyfs = keyfs
        self.relpath = relpath
        self.type = type
        self.name = name

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
        self.at_serial = keyfs.get_next_serial() - 1
        self.cache = {}
        self.dirty = set()

    def exists_typed_state(self, typedkey):
        try:
            self.keyfs.get_value_at(typedkey, self.at_serial)
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
                        fswriter.record_delete(typedkey)
                    else:
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
