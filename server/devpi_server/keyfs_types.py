from __future__ import annotations

from .markers import Absent
from .markers import Deleted
from .readonly import ensure_deeply_readonly
from attrs import define
from attrs import frozen
from typing import TYPE_CHECKING
import contextlib
import re
import warnings


if TYPE_CHECKING:
    from typing import Any


@frozen
class Record:
    key: PTypedKey | TypedKey
    value: Any
    back_serial: int
    old_value: Any

    def __attrs_post_init__(self):
        if (
            self.value is not None
            and not isinstance(self.old_value, (Absent, Deleted, type(None)))
            and not isinstance(ensure_deeply_readonly(self.value), type(self.old_value))
        ):
            msg = f"Mismatching types for value {self.value!r} and old_value {self.old_value!r}"
            raise TypeError(msg)


@define
class RelpathInfo:
    relpath: str
    keyname: str
    serial: int
    back_serial: int
    value: Any


class PTypedKey:
    __slots__ = ('keyfs', 'name', 'pattern', 'rex_reverse', 'type')
    rex_braces = re.compile(r'\{(.+?)\}')

    def __init__(self, keyfs, key, type, name):
        self.keyfs = keyfs
        assert isinstance(key, str)
        self.pattern = key
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

    def on_key_change(self, callback):
        self.keyfs.notifier.on_key_change(self.name, callback)

    def __repr__(self):
        return f"<PTypedKey {self.pattern!r} type {self.type.__name__!r}>"


class TypedKey:
    __slots__ = ('keyfs', 'name', 'params', 'relpath', 'type')

    def __init__(self, keyfs, relpath, type, name, params=None):
        self.keyfs = keyfs
        self.relpath = relpath
        self.type = type
        self.name = name
        self.params = params or {}

    def __hash__(self):
        return hash(self.relpath)

    def __eq__(self, other):
        return self.relpath == other.relpath

    def __repr__(self):
        return f"<TypedKey {self.name} {self.type.__name__} {self.relpath}>"

    def get(self, *, readonly=None):
        if readonly is None:
            readonly = True
        else:
            warnings.warn(
                "The 'readonly' argument is deprecated. "
                "You should either drop it or use the 'get_mutable' method.",
                stacklevel=2,
            )
        if readonly:
            return self.keyfs.tx.get(self)
        return self.keyfs.tx.get_mutable(self)

    def get_mutable(self):
        return self.keyfs.tx.get_mutable(self)

    @property
    def last_serial(self):
        try:
            return self.keyfs.tx.last_serial(self)
        except KeyError:
            return None

    def is_dirty(self):
        return self.keyfs.tx.is_dirty(self)

    @contextlib.contextmanager
    def update(self):
        val = self.keyfs.tx.get_mutable(self)
        yield val
        # no exception, so we can set and thus mark dirty the object
        self.set(val)

    def set(self, val):
        if not isinstance(val, self.type):
            raise TypeError(
                "%r requires value of type %r, got %r" % (
                    self.relpath, self.type.__name__, type(val).__name__))
        self.keyfs.tx.set(self, val)

    def exists(self):
        return self.keyfs.tx.exists(self)

    def delete(self):
        return self.keyfs.tx.delete(self)
