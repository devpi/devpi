
import urllib
import pytest
import py
from devpi import config
from devpi import log
from devpi.main import Hub

class TestUnit:
    def test_getdict_with_defaults(self):
        from devpi.index import getdict
        d = getdict([])
        assert d["upstreams"] == ["int/dev", "ext/pypi"]

        d = getdict(["upstreams=int/dev,bob/dev"])
        assert d["upstreams"] == ["int/dev", "bob/dev"]

        d = getdict(["upstreams="])
        assert d["upstreams"] == []

        pytest.raises(KeyError, lambda: getdict(["qwe=qwe"]))



