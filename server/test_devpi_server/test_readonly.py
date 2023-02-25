from collections.abc import Mapping
from collections.abc import Sequence
from collections.abc import Set
from devpi_server.readonly import ensure_deeply_readonly
from devpi_server.readonly import get_mutable_deepcopy
from devpi_server.readonly import is_deeply_readonly
from devpi_server.readonly import is_sequence
import pytest


class TestEnsureDeeplyReadonly:
    def test_bool(self) -> None:
        result = ensure_deeply_readonly(True)
        assert isinstance(result, bool)
        assert result is True

    def test_frozenset(self) -> None:
        result = ensure_deeply_readonly(frozenset({1}))
        assert isinstance(result, frozenset)
        assert result == frozenset({1})


class TestGetMutableDeepcopy:
    def test_frozenset(self) -> None:
        result = get_mutable_deepcopy(frozenset({1}))
        assert isinstance(result, frozenset)
        assert result == frozenset({1})


class TestDictReadonlyView:
    def test_type(self) -> None:
        assert isinstance(ensure_deeply_readonly({}), Mapping)

    def test_nonzero(self) -> None:
        assert not ensure_deeply_readonly({})
        assert ensure_deeply_readonly({1: 2})

    def test_simple(self) -> None:
        d = {1: 2}
        r = ensure_deeply_readonly(d)
        assert r[1] == 2
        with pytest.raises(KeyError):
            r[2]
        assert len(r) == 1
        assert r == d
        assert not (r != d)  # noqa: SIM202 - we want to check __ne__

    def test_recursive(self) -> None:
        d: dict = {1: []}
        r = ensure_deeply_readonly(d)
        assert r[1] == []
        with pytest.raises(AttributeError):
            r[1].append(1)

    def test_update(self) -> None:
        d = {1: 2}
        d.update(ensure_deeply_readonly({2: 3}))
        assert d == {1: 2, 2: 3}

    def test_values(self) -> None:
        d = ensure_deeply_readonly({1: []})
        (value,) = d.values()
        assert is_deeply_readonly(value)


class TestSetReadonlyView:
    def test_type(self) -> None:
        assert isinstance(ensure_deeply_readonly(set()), Set)

    def test_nonzero(self) -> None:
        assert not ensure_deeply_readonly(set())
        assert ensure_deeply_readonly(set([1]))

    def test_simple(self) -> None:
        x: set = set()
        assert not is_deeply_readonly(x)
        r = ensure_deeply_readonly(x)
        assert is_deeply_readonly(r)
        assert not r
        assert "x" not in r
        with pytest.raises(AttributeError):
            r.add(2)
        assert len(r) == 0

    def test_nogetitem(self) -> None:
        with pytest.raises(TypeError):
            ensure_deeply_readonly(set([1, 2]))[0]

    def test_iter(self) -> None:
        l = list(ensure_deeply_readonly(set([1, 2])))
        assert l == [1, 2]


class TestListReadonlyView:
    def test_type(self) -> None:
        assert isinstance(ensure_deeply_readonly([]), Sequence)

    def test_nonzero(self) -> None:
        assert not ensure_deeply_readonly([])
        assert ensure_deeply_readonly([1])

    def test_simple(self) -> None:
        x = [1]
        assert not is_deeply_readonly(x)
        r = ensure_deeply_readonly(x)
        assert r
        assert is_deeply_readonly(r)
        assert len(r) == 1
        with pytest.raises(AttributeError):
            r.append(2)
        c = get_mutable_deepcopy(r)
        assert c == x
        c.append(1)
        assert c != x

    def test_recursive(self) -> None:
        x = [[1]]
        r = ensure_deeply_readonly(x)
        y = r[0]
        with pytest.raises(AttributeError):
            y.append(2)
        assert y == [1]


class TestTupleReadonlyView:
    def test_type(self) -> None:
        assert isinstance(ensure_deeply_readonly(()), Sequence)

    def test_nonzero(self) -> None:
        assert not ensure_deeply_readonly(())
        assert ensure_deeply_readonly((1,))

    def test_simple(self) -> None:
        x = (1,)
        assert not is_deeply_readonly(x)
        r = ensure_deeply_readonly(x)
        assert is_deeply_readonly(r)
        assert r
        assert len(r) == 1
        assert r[0] == 1
        c = get_mutable_deepcopy(r)
        assert c == x

    def test_recursive(self) -> None:
        x = ([1],)
        r = ensure_deeply_readonly(x)
        with pytest.raises(AttributeError):
            r[0].append(2)
        assert r[0] == [1]


def test_is_sequence() -> None:
    assert is_sequence([])
    assert is_sequence(())
    assert is_sequence(ensure_deeply_readonly(()))
    assert is_sequence(ensure_deeply_readonly([]))
