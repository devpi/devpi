from __future__ import annotations

from .markers import Absent
from .markers import Deleted
from .readonly import ensure_deeply_readonly
from attrs import define
from attrs import frozen
from collections.abc import Hashable
from typing import Generic
from typing import NewType
from typing import TYPE_CHECKING
from typing import TypeVar
from typing import Union
from typing import overload
import contextlib
import re
import warnings


if TYPE_CHECKING:
    from .keyfs import KeyFS
    from .normalized import NormalizedName
    from .readonly import DictViewReadonly
    from .readonly import ListViewReadonly
    from .readonly import SetViewReadonly
    from .readonly import TupleViewReadonly
    from collections.abc import Iterator
    from typing import Any
    from typing import Literal

    KeyFSTypesRO = Union[
        bool,
        bytes,
        DictViewReadonly,
        float,
        frozenset,
        int,
        ListViewReadonly,
        SetViewReadonly,
        str,
        TupleViewReadonly,
    ]


KeyFSTypes = Union[bool, bytes, dict, float, frozenset, int, list, set, str, tuple]
KeyType = TypeVar("KeyType")


@frozen
class Record(Generic[KeyType]):
    key: PTypedKey[KeyType] | TypedKey[KeyType]
    value: KeyType
    back_serial: int
    old_value: KeyFSTypesRO | None

    def __attrs_post_init__(self) -> None:
        if (value := self.value) is not None:
            if not isinstance(value, self.key.type):
                msg = f"Mismatching value type {type(value)} for record with {self.key}"
                raise TypeError(msg)
            if not isinstance(
                self.old_value, (Absent, Deleted, type(None))
            ) and not isinstance(ensure_deeply_readonly(value), type(self.old_value)):
                msg = f"Mismatching types for value {value!r} and old_value {self.old_value!r}"
                raise TypeError(msg)


RelPath = NewType("RelPath", str)


@define
class RelpathInfo:
    relpath: RelPath
    keyname: str
    serial: int
    back_serial: int
    value: Any


@define
class FilePathInfo:
    relpath: RelPath
    hash_digest: str | None

    def __eq__(self, other: object) -> bool:
        if isinstance(other, FilePathInfo):
            return self.relpath == other.relpath
        return False

    def __hash__(self) -> int:
        return hash(self.relpath)


class PTypedKey(Generic[KeyType]):
    __slots__ = ('keyfs', 'name', 'pattern', 'rex_reverse', 'type')
    rex_braces = re.compile(r'\{(.+?)\}')

    def __init__(
        self,
        keyfs: KeyFS,
        key: str,
        key_type: type[KeyType],
        name: str,
    ) -> None:
        self.keyfs = keyfs
        assert isinstance(key, str)
        self.pattern = key
        self.type: type[KeyType] = key_type
        self.name = name

        def repl(match):
            name = match.group(1)
            return r'(?P<%s>[^\/]+)' % name
        rex_pattern = self.pattern.replace("+", r"\+")
        rex_pattern = self.rex_braces.sub(repl, rex_pattern)
        self.rex_reverse = re.compile("^" + rex_pattern + "$")

    def __call__(self, **kw: NormalizedName | str) -> TypedKey[KeyType]:
        for val in kw.values():
            if "/" in val:
                raise ValueError(val)
        relpath = self.pattern.format(**kw)
        return TypedKey(self.keyfs, RelPath(relpath), self.type, self.name, params=kw)

    def extract_params(self, relpath):
        m = self.rex_reverse.match(relpath)
        return m.groupdict() if m is not None else {}

    def on_key_change(self, callback):
        self.keyfs.notifier.on_key_change(self.name, callback)

    def __repr__(self):
        return f"<PTypedKey {self.pattern!r} type {self.type.__name__!r}>"


H = TypeVar("H", bound=Hashable)


class TypedKey(Generic[KeyType]):
    __slots__ = ('keyfs', 'name', 'params', 'relpath', 'type')

    def __init__(
        self,
        keyfs: KeyFS,
        relpath: RelPath,
        key_type: type[KeyType],
        name: str,
        params: dict | None = None,
    ) -> None:
        self.keyfs = keyfs
        self.relpath = relpath
        self.type: type[KeyType] = key_type
        self.name = name
        self.params = params or {}

    def __hash__(self):
        return hash(self.relpath)

    def __eq__(self, other):
        return self.relpath == other.relpath

    def __repr__(self):
        return f"<TypedKey {self.name} {self.type.__name__} {self.relpath}>"

    @overload
    def get(self: TypedKey[bool], *, readonly: None = None) -> bool: ...

    @overload
    def get(self: TypedKey[bytes], *, readonly: None = None) -> bytes: ...

    @overload
    def get(self: TypedKey[dict], *, readonly: None = None) -> DictViewReadonly: ...

    @overload
    def get(self: TypedKey[float], *, readonly: None = None) -> float: ...

    @overload
    def get(self: TypedKey[frozenset], *, readonly: None = None) -> frozenset: ...

    @overload
    def get(self: TypedKey[int], *, readonly: None = None) -> int: ...

    @overload
    def get(self: TypedKey[list], *, readonly: None = None) -> ListViewReadonly: ...

    @overload
    def get(self: TypedKey[set], *, readonly: None = None) -> SetViewReadonly: ...

    @overload
    def get(self: TypedKey[str], *, readonly: None = None) -> str: ...

    @overload
    def get(self: TypedKey[tuple], *, readonly: None = None) -> TupleViewReadonly: ...

    @overload
    def get(self: TypedKey[bool], *, readonly: Literal[True]) -> bool: ...

    @overload
    def get(self: TypedKey[bytes], *, readonly: Literal[True]) -> bytes: ...

    @overload
    def get(self: TypedKey[dict], *, readonly: Literal[True]) -> DictViewReadonly: ...

    @overload
    def get(self: TypedKey[float], *, readonly: Literal[True]) -> float: ...

    @overload
    def get(self: TypedKey[frozenset], *, readonly: Literal[True]) -> frozenset: ...

    @overload
    def get(self: TypedKey[int], *, readonly: Literal[True]) -> int: ...

    @overload
    def get(self: TypedKey[list], *, readonly: Literal[True]) -> ListViewReadonly: ...

    @overload
    def get(
        self: TypedKey[set[H]], *, readonly: Literal[True]
    ) -> SetViewReadonly[H]: ...

    @overload
    def get(self: TypedKey[str], *, readonly: Literal[True]) -> str: ...

    @overload
    def get(self: TypedKey[tuple], *, readonly: Literal[True]) -> TupleViewReadonly: ...

    @overload
    def get(self: TypedKey[bool], *, readonly: Literal[False]) -> bool: ...

    @overload
    def get(self: TypedKey[bytes], *, readonly: Literal[False]) -> bytes: ...

    @overload
    def get(self: TypedKey[dict], *, readonly: Literal[False]) -> dict: ...

    @overload
    def get(self: TypedKey[float], *, readonly: Literal[False]) -> float: ...

    @overload
    def get(self: TypedKey[frozenset], *, readonly: Literal[False]) -> frozenset: ...

    @overload
    def get(self: TypedKey[int], *, readonly: Literal[False]) -> int: ...

    @overload
    def get(self: TypedKey[list], *, readonly: Literal[False]) -> list: ...

    @overload
    def get(self: TypedKey[set], *, readonly: Literal[False]) -> set: ...

    @overload
    def get(self: TypedKey[str], *, readonly: Literal[False]) -> str: ...

    @overload
    def get(self: TypedKey[tuple], *, readonly: Literal[False]) -> tuple: ...

    def get(self, *, readonly: bool | None = None) -> KeyFSTypesRO | KeyFSTypes:
        if readonly is None:
            readonly = True
        else:
            warnings.warn(
                "The 'readonly' argument is deprecated. "
                "You should either drop it or use the 'get_mutable' method.",
                DeprecationWarning,
                stacklevel=2,
            )
        if readonly:
            return self.keyfs.tx.get(self)
        return self.keyfs.tx.get_mutable(self)

    def get_mutable(self) -> KeyType:
        return self.keyfs.tx.get_mutable(self)

    @property
    def last_serial(self) -> int | None:
        try:
            return self.keyfs.tx.last_serial(self)
        except KeyError:
            return None

    def is_dirty(self) -> bool:
        return self.keyfs.tx.is_dirty(self)

    @contextlib.contextmanager
    def update(self) -> Iterator[KeyType]:
        val = self.keyfs.tx.get_mutable(self)
        yield val
        # no exception, so we can set and thus mark dirty the object
        self.set(val)

    def set(self, val: KeyType) -> None:
        if not isinstance(val, self.type):
            raise TypeError(
                "%r requires value of type %r, got %r" % (
                    self.relpath, self.type.__name__, type(val).__name__))
        self.keyfs.tx.set(self, val)

    def exists(self):
        return self.keyfs.tx.exists(self)

    def delete(self):
        return self.keyfs.tx.delete(self)
