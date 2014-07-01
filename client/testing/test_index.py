
import pytest
from devpi.index import *

def test_index_show_empty(loghub):
    with pytest.raises(SystemExit):
        index_show(loghub, None)
    loghub._getmatcher().fnmatch_lines("*no index specified*")


@pytest.mark.parametrize("key", ("acl_upload", "bases", "pypi_whitelist"))
@pytest.mark.parametrize("value, result", (
    ("", []), ("x,y", ["x", "y"]), ("x,,y", ["x", "y"])))
def test_parse_keyvalue_spec_index(loghub, key, value, result):
    kvdict = parse_keyvalue_spec_index(loghub, ["%s=%s" % (key, value)])
    assert kvdict[key] == result
