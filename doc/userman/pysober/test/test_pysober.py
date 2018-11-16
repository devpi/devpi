
from pysober import __version__

def test_version(pysober_expected_version):
    assert pysober_expected_version == __version__
