"""

basic mechanics for turning a mutable dict/list/seq/tuple
into a readonly view.
"""
from abc import ABC, abstractmethod
from functools import singledispatch
from functools import total_ordering
from typing import AbstractSet
from typing import Any
from typing import Hashable
from typing import ItemsView
from typing import Iterator
from typing import KeysView
from typing import Mapping
from typing import Union
from typing import Sequence
from typing import Tuple
from typing import ValuesView
from typing import overload


_immutable = (bool, bytes, float, frozenset, int, str, type(None))


class ReadonlyView(ABC):
    __slots__ = ('_data',)
    _data: Any

    @abstractmethod
    def __init__(self) -> None:
        raise NotImplementedError

    def __eq__(self, other: Any) -> bool:
        if isinstance(other, ReadonlyView):
            other = other._data
        return self._data == other

    def __lt__(self, other: Any) -> bool:
        if isinstance(other, ReadonlyView):
            other = other._data
        return self._data < other

    def __contains__(self, key: Hashable) -> bool:
        return key in self._data

    def __len__(self) -> int:
        return len(self._data)

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self._data!r})"


Readonly = Union[
    None, bool, bytes, float, frozenset, int, str,
    'DictViewReadonly', 'ListViewReadonly',
    'SetViewReadonly', 'TupleViewReadonly']


@total_ordering
class DictViewReadonly(ReadonlyView, Mapping[Hashable, Readonly]):
    __slots__ = ()

    def __init__(self, data: dict) -> None:
        self._data = data

    def __iter__(self) -> Iterator:
        return iter(self._data)

    def __getitem__(self, key: Hashable) -> Readonly:
        return ensure_deeply_readonly(self._data[key])

    def items(self) -> ItemsView[Hashable, Readonly]:
        return DictItemsViewReadonly(self)

    def keys(self) -> KeysView[Hashable]:
        return self._data.keys()

    @overload
    def get(self, key: Hashable) -> Readonly:
        pass

    @overload
    def get(self, key: Hashable, default: Union[Readonly, Any]) -> Readonly:
        pass

    def get(self, key: Hashable, default: Union[Readonly, Any] = None) -> Readonly:
        val = self._data.get(key, default)
        return ensure_deeply_readonly(val)

    def values(self) -> ValuesView[Readonly]:
        return DictValuesViewReadonly(self)


class DictItemsViewReadonly(ItemsView[Hashable, Readonly]):
    __slots__ = ()
    _mapping: DictViewReadonly

    def __iter__(self) -> Iterator[Tuple[Hashable, Readonly]]:
        for x, y in self._mapping._data.items():
            yield (x, ensure_deeply_readonly(y))


class DictValuesViewReadonly(ValuesView[Readonly]):
    __slots__ = ()
    _mapping: DictViewReadonly

    def __iter__(self) -> Iterator[Readonly]:
        yield from (ensure_deeply_readonly(x) for x in self._mapping._data.values())


class SeqViewReadonly(ReadonlyView, ABC, Sequence[Readonly]):
    __slots__ = ()

    @abstractmethod
    def __init__(self) -> None:
        raise NotImplementedError

    def __iter__(self) -> Iterator[Readonly]:
        for x in self._data:
            yield ensure_deeply_readonly(x)

    @overload
    def __getitem__(self, key: int) -> Readonly:
        pass

    @overload
    def __getitem__(self, key: slice) -> Sequence[Readonly]:
        pass

    def __getitem__(self, key: Union[int, slice]) -> Union[Readonly, Sequence[Readonly]]:
        return ensure_deeply_readonly(self._data[key])


@total_ordering
class ListViewReadonly(SeqViewReadonly):
    __slots__ = ()

    def __init__(self, data: list) -> None:
        self._data = data


class SetViewReadonly(ReadonlyView, AbstractSet):
    __slots__ = ()

    def __init__(self, data: AbstractSet) -> None:
        self._data = data

    def __iter__(self) -> Iterator[Hashable]:
        return iter(self._data)


@total_ordering
class TupleViewReadonly(SeqViewReadonly):
    __slots__ = ()

    def __init__(self, data: tuple) -> None:
        self._data = data


@singledispatch
def ensure_deeply_readonly(val: Any) -> Any:
    raise ValueError("don't know how to handle type %r" % type(val))


@ensure_deeply_readonly.register
def _(val: ReadonlyView) -> ReadonlyView:
    return val


@ensure_deeply_readonly.register
def _(val: None) -> None:
    return val


@ensure_deeply_readonly.register
def _(val: bool) -> bool:
    return val


@ensure_deeply_readonly.register
def _(val: bytes) -> bytes:
    return val


@ensure_deeply_readonly.register
def _(val: dict) -> DictViewReadonly:
    return DictViewReadonly(val)


@ensure_deeply_readonly.register
def _(val: float) -> float:
    return val


@ensure_deeply_readonly.register
def _(val: frozenset) -> frozenset:
    return val


@ensure_deeply_readonly.register
def _(val: int) -> int:
    return val


@ensure_deeply_readonly.register
def _(val: list) -> ListViewReadonly:
    return ListViewReadonly(val)


@ensure_deeply_readonly.register
def _(val: set) -> SetViewReadonly:
    return SetViewReadonly(val)


@ensure_deeply_readonly.register
def _(val: str) -> str:
    return val


@ensure_deeply_readonly.register
def _(val: tuple) -> TupleViewReadonly:
    return TupleViewReadonly(val)


@singledispatch
def get_mutable_deepcopy(val: Any) -> Any:
    """ return a deep copy of ``val`` so that there is no sharing
    of mutable data between val and the returned copy."""
    raise ValueError("don't know how to handle type %r" % type(val))


@get_mutable_deepcopy.register
def _(val: ReadonlyView) -> ReadonlyView:
    return get_mutable_deepcopy(val._data)


@get_mutable_deepcopy.register
def _(val: None) -> None:
    return val


@get_mutable_deepcopy.register
def _(val: bool) -> bool:
    return val


@get_mutable_deepcopy.register
def _(val: bytes) -> bytes:
    return val


@get_mutable_deepcopy.register
def _(val: dict) -> dict:
    return {k: get_mutable_deepcopy(v) for k, v in val.items()}


@get_mutable_deepcopy.register
def _(val: float) -> float:
    return val


@get_mutable_deepcopy.register
def _(val: frozenset) -> frozenset:
    return val


@get_mutable_deepcopy.register
def _(val: int) -> int:
    return val


@get_mutable_deepcopy.register
def _(val: list) -> list:
    return [get_mutable_deepcopy(item) for item in val]


@get_mutable_deepcopy.register
def _(val: set) -> set:
    return {item for item in val}


@get_mutable_deepcopy.register
def _(val: str) -> str:
    return val


@get_mutable_deepcopy.register
def _(val: tuple) -> tuple:
    return tuple(get_mutable_deepcopy(item) for item in val)


def is_deeply_readonly(val: Any) -> bool:
    """ Return True if the value is either immutable or a readonly proxy
    (which ensures only reading of data is possible). """
    return isinstance(val, (ReadonlyView, _immutable))


def is_sequence(val: Any) -> bool:
    """ Return True if the value is a readonly or normal sequence (list, tuple)"""
    return isinstance(val, (SeqViewReadonly, list, tuple))
