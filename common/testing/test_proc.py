import pytest
import py
from devpi_common.proc import *

@pytest.fixture
def hg():
    hg = py.path.local.sysfind("hg")
    if not hg:
        pytest.skip("no hg")
    return str(hg)

def test_check_output(hg):
    assert check_output([hg, "--version"])

def test_checkoutput_error(hg):
    with pytest.raises(CalledProcessError):
        check_output([hg, "qlwkje"])

