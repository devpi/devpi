
from devpi_common.types import *

def test_CompareMixin():
    class A(CompareMixin):
        def __init__(self, count):
            self.cmpval = count
    l = list(map(A, range(10)))
    assert max(reversed(l)).cmpval == 9
