"""

filesystem key/value storage with support for
storing basic python types.

"""

import re
import py
import threading
from tempfile import NamedTemporaryFile
from execnet import dumps, loads
import os
from os.path import basename, isabs, join

_nodefault = object()

class KeyFS:
    def __init__(self, basedir):
        self.basedir = py.path.local(basedir)
        self.tmpdir = str(self.basedir.ensure(".tmp", dir=1))
        self.keys = []
        self._locks = {}

    def _getlock(self, relpath):
        return self._locks.setdefault(relpath, threading.RLock())

    def _get(self, relpath, default=_nodefault):
        path = self._getpath(relpath)
        try:
            with path.open("rb") as f:
                return f.read()
        except py.error.ENOENT:
            if default is _nodefault:
                raise KeyError(relpath)
            return default

    def tempfile(self, prefix):
        f = NamedTemporaryFile(prefix=prefix, dir=self.tmpdir, delete=False)
        relpath = os.path.relpath(f.name, str(self.basedir))
        f.key = TypedKey(self, relpath, bytes)
        return f

    def _set(self, relpath, value):
        with self.tempfile(basename(relpath)) as f:
            f.write(value)
        self._rename(f.key.relpath, relpath)
        return True

    def _rename(self, sourcekey, destkey):
        assert not isabs(sourcekey), sourcekey
        assert not isabs(destkey), destkey
        source = join(str(self.basedir), sourcekey)
        dest = join(str(self.basedir), destkey)
        try:
            os.rename(source, dest)
        except OSError as e:
            os.makedirs(os.path.dirname(dest))
            os.rename(source, dest)

    def _delete(self, relpath):
        path = self._getpath(relpath)
        try:
            path.remove()
        except py.error.ENOENT:
            return False
        return True

    def _exists(self, relpath):
        path = self._getpath(relpath)
        return path.check()

    def _getpath(self, relpath):
        assert isinstance(relpath, (str, unicode)), (type(relpath), relpath)
        return self.basedir.join(relpath)

    def destroyall(self):
        if self.basedir.check():
            self.basedir.remove()

    def addkey(self, key, type):
        if "{" in key:
            key = PTypedKey(self, key, type)
        else:
            key = TypedKey(self, key, type)
        self.keys.append(key)
        return key


class PTypedKey:
    def __init__(self, keyfs, key, type):
        self.keyfs = keyfs
        self.key = key
        self.type = type

    def __call__(self, **kw):
        newkw = {}
        for name, val in kw.items():
            if py.builtin._istext(val):
                val = val.encode("utf8")
            else:
                assert py.builtin._isbytes(val)
            newkw[name] = val
        realkey = self.key.format(**newkw)
        return TypedKey(self.keyfs, realkey, self.type)

    def listnames(self, __name, **kw):
        expected = "/{" + __name + "}"
        if not self.key.endswith(expected):
            raise KeyError("%r does not end with %r" % (self.key, expected))
        basekey = self.key[:-len(expected)].format(**kw)
        path = self.keyfs._getpath(basekey)
        try:
            return set(os.listdir(str(path)))
        except OSError as e:
            if e.errno == 2:
                return set()
            raise

    def __repr__(self):
        return "<PTypedKey %r type %r>" %(self.key, self.type.__name__)


class TypedKey:
    def __init__(self, keyfs, relpath, type):
        self.keyfs = keyfs
        self.relpath = relpath
        self.type = type

    @property
    def filepath(self):
        return self.keyfs._getpath(self.relpath)

    def __repr__(self):
        return "<TypedKey %r type %r>" %(self.relpath, self.type.__name__)

    def get(self, default=_nodefault):
        try:
            data = self.keyfs._get(self.relpath)
        except KeyError:
            if default == _nodefault:
                return self.type()
            return default
        if self.type == bytes:
            return data
        val = loads(data)
        assert isinstance(val, self.type), val
        return val

    def set(self, val):
        if not isinstance(val, self.type):
            raise TypeError("%r requires value of type %r, got %r" %(
                            self.relpath, self.type.__name__,
                            type(val).__name__))
        if self.type == bytes:
            data = val
        else:
            data = dumps(val)
        self.keyfs._set(self.relpath, data)

    def exists(self):
        return self.keyfs._exists(self.relpath)

    def delete(self):
        return self.keyfs._delete(self.relpath)

    def move(self, destkey):
        if self.type != destkey.type:
            raise TypeError("key %r has type %r, destkey %r has type %r" % (
                            self.relpath, self.type.__name__,
                            destkey.relpath, destkey.type.__name__))
        self.keyfs._rename(self.relpath, destkey.relpath)

    def locked_update(self):
        return LockedUpdate(self)

    def update(self):
        return Update(self)

class Update:
    def __init__(self, typedkey):
        self.typedkey = typedkey

    def __enter__(self):
        self._val = val = self.typedkey.get()
        return val

    def __exit__(self, type, val, tb):
        if not type:
            self.typedkey.set(self._val)

class LockedUpdate:
    def __init__(self, typedkey):
        self.typedkey = typedkey
        self.rlock = self.typedkey.keyfs._getlock(self.typedkey.relpath)

    def __enter__(self):
        self.rlock.acquire()
        try:
            self._val = self.typedkey.get()
            return self._val
        except:
            self.rlock.release()
            raise

    def __exit__(self, type, val, tb):
        try:
            if not type:
                self.typedkey.set(self._val)
        finally:
            self.rlock.release()
