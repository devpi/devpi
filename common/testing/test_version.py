import pytest

from devpi_common.version import *

@pytest.mark.parametrize(("releasename", "expected"), [
    ("pytest-2.3.4.zip", ("pytest", "2.3.4")),
    ("green-0.4.0-py2.5-win32.egg", ("green", "0.4.0")),
])
def test_guess_pkgname_and_version(releasename, expected):
    result = guess_pkgname_and_version(releasename)
    assert result == (expected[0], Version(expected[1]))

def test_normversion():
    n1 = normversion("1.0")
    n2 = normversion("1.0.alpha")
    #assert str(n2) == "1.0a0"
    #assert str(n1) == "1.0"
    assert n1 > n2

    assert normversion("1.0-static") > n1

@pytest.mark.parametrize(("releasename", "expected"), [
    ("pytest-2.3.4.zip", ("pytest", "2.3.4", ".zip")),
    ("http://x/pytest-2.3.4.zip", ("pytest", "2.3.4", ".zip")),
    ("green-0.4.0-py2.5-win32.egg", ("green", "0.4.0", "-py2.5-win32.egg")),
    # invalid package file names
    ("fixture.html", ("fixture.html", "", "")),
    ("fixture-2.4.html", ("fixture", "2.4.html", "")),
    ("fixture2.4.html", ("fixture2.4.html", "", "")),
])
def test_splitbasename(releasename, expected):
    result = splitbasename(releasename)
    assert result == expected


class TestVersion:
    def test_basic_sorting(self):
        ver1 = Version("1.3")
        ver2 = Version("1.4dev1")
        ver3 = Version("1.4")
        assert ver1 < ver2 < ver3

    def test_nonpepversion(self):
        ver1 = Version("1.0-static")
        pytest.raises(ValueError, ver1.autoinc)

    def test_str(self):
        ver1 = Version("1.3")
        assert str(ver1) == "1.3"
        assert "1.3" in repr(ver1)

    def test_autoinc(self):
        ver = Version("1.3dev1")
        newver = ver.autoinc()
        assert str(newver) == "1.3.dev2"

        ver = Version("1.3a1")
        newver = ver.autoinc()
        assert str(newver) == "1.3a2"

        ver = Version("1.3")
        pytest.raises(ValueError, lambda: ver.autoinc())
