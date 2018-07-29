from devpi.index import index_show
import pytest


def test_index_show_empty(loghub):
    with pytest.raises(SystemExit):
        index_show(loghub, None)
    loghub._getmatcher().fnmatch_lines("*no index specified*")
