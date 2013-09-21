
from devpi_server.types import *

def test_gencomparison_with_key():
    class A:
        def __init__(self, count):
            self.count = count
    gen_comparisons_with_key(A, "count")
    assert max(reversed(map(A, range(10)))).count == 9

def test_CompareMixin():
    class A(CompareMixin):
        def __init__(self, count):
            self.cmpval = count
    assert max(reversed(map(A, range(10)))).cmpval == 9
