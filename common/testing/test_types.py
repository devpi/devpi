
from devpi_common.types import *

def test_CompareMixin():
    class A(CompareMixin):
        def __init__(self, count):
            self.cmpval = count
    l = list(map(A, range(10)))
    assert max(reversed(l)).cmpval == 9


def test_ensure_unicode_keys():
    d = {b"hello": "world"}
    ensure_unicode_keys(d)
    assert py.builtin._istext(list(d)[0])
    assert d[u"hello"] == "world"
