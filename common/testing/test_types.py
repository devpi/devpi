
from devpi_common.types import *

def test_CompareMixin():
    class A(CompareMixin):
        def __init__(self, count):
            self.cmpval = count
    assert max(reversed(map(A, range(10)))).cmpval == 9
