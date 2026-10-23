from __future__ import annotations

from devpi_server.keyfs_types import RelPath
import pytest


@pytest.mark.parametrize(("relpath", "match_str"), [
    ("../foo", "must not contain"),
    ("./foo", "must not contain"),
    ("/absolute", "must be relative"),
    ("foo/.", "must not contain"),
    ("foo/..", "must not contain"),
])
def test_invalid_relpath(match_str: str, relpath: str) -> None:
    with pytest.raises(ValueError, match=match_str):
        RelPath(relpath)
