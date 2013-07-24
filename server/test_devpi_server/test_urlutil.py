import pytest
from devpi_server.urlutil import *

class TestDistURL:
    def test_basename(self):
        d = DistURL("http://codespeak.net/basename")
        assert d.basename == "basename"
        d = DistURL("http://codespeak.net")
        assert not d.basename

    def test_repr(self):
        d = DistURL("http://host.com/path")
        assert repr(d) == "<DistURL url='http://host.com/path'>"


    def test_parentbasename(self):
        d = DistURL("http://codespeak.net/simple/basename/")
        assert d.parentbasename == "basename"
        assert d.basename == ""

    def test_hashing(self):
        assert hash(DistURL("http://a")) == hash(DistURL("http://a"))
        assert DistURL("http://a") == DistURL("http://a")

    def test_eggfragment(self):
        url = DistURL("http://a/py.tar.gz#egg=py-dev")
        assert url.eggfragment == "py-dev"

    def test_md5(self):
        url = DistURL("http://a/py.tar.gz#md5=123123")
        assert url.md5 == "123123"

    def test_joinpath(self):
        url = DistURL("http://a/sub/index.html#md5=123123")
        assert url.joinpath("../pkg/x.zip") == "http://a/pkg/x.zip"

    def test_geturl_nofrag(self):
        url = DistURL("http://a/py.tar.gz#egg=py-dev")
        assert url.geturl_nofragment() == "http://a/py.tar.gz"

    def test_url_nofrag(self):
        url = DistURL("http://a/py.tar.gz#egg=py-dev")
        res = url.url_nofrag
        assert not isinstance(res, DistURL)
        assert res == "http://a/py.tar.gz"

    def test_versionapi(self):
        url = DistURL("http://a/py-1.0.tar.gz")
        assert url.pkgname_and_version == ("py", "1.0")

    def test_easyversion_comparison(self):
        url1 = DistURL("http://a/py-1.0.tar.gz")
        url2 = DistURL("http://a/py-1.0.dev1.tar.gz")
        url3 = DistURL("http://a/py.zip#egg=py-dev")
        assert url3.easyversion > url1.easyversion > url2.easyversion
        assert url3 > url1 > url2


@pytest.mark.parametrize(("url", "path", "expected"), [
    ("http://x/simple", "pytest", "http://x/pytest"),
    ("http://x/simple/", "pytest", "http://x/simple/pytest"),
    ("http://x/simple/", "pytest/", "http://x/simple/pytest/"),
    ("http://x/simple/", "pytest/", "http://x/simple/pytest/")
])
def test_joinpath(url, path, expected):
    new = joinpath(url, path)
    assert new == expected

def test_joinpath_multiple():
    url = "http://x/simple/"
    new = joinpath(url, "package", "version")
    assert new == "http://x/simple/package/version"

@pytest.mark.parametrize(("releasename", "expected"), [
    ("pytest-2.3.4.zip", ("pytest", "2.3.4", ".zip")),
    ("pytest-2.3.4-py27.egg", ("pytest", "2.3.4", "-py27.egg")),
    ("dddttt-0.1.dev38-py2.7.egg", ("dddttt", "0.1.dev38", "-py2.7.egg")),
    ("green-0.4.0-py2.5-win32.egg", ("green", "0.4.0", "-py2.5-win32.egg")),
])
def test_splitbasename(releasename, expected):
    result = splitbasename(releasename)
    assert result == expected
    #assert DistURL("http://hello/%s" % releasename).splitbasename() == expected

@pytest.mark.parametrize(("releasename", "expected"), [
    ("x-2.3.zip", ("source", "sdist")),
    ("x-2.3-0.4.0.win32-py3.1.exe", ("3.1", "bdist_wininst")),
    ("x-2.3-py27.egg", ("2.7", "bdist_egg")),
    ("greenlet-0.4.0-py3.3-win-amd64.egg", ("3.3", "bdist_egg")),
])
def test_get_pyversion_filetype(releasename, expected):
    result = get_pyversion_filetype(releasename)
    assert result == expected
    #assert DistURL("http://hello/%s" % releasename).splitbasename() == expected

@pytest.mark.parametrize(("releasename", "expected"), [
    ("pytest-2.3.4.zip", ("pytest-2.3.4", ".zip")),
    ("green-0.4.0-py2.5-win32.egg", ("green-0.4.0-py2.5-win32", ".egg")),
    ("green-1.0.tar.gz", ("green-1.0", ".tar.gz")),
])
def test_splitext_archive(releasename, expected):
    url = DistURL("http://hello/%s" % releasename)
    assert url.splitext_archive() == expected



#
# test torelpath/fromrelpath
#

@pytest.mark.parametrize("url", [
    "http://codespeak.net", "https://codespeak.net",
    "http://codespeak.net/path",
    "http://codespeak.net:3123/path",
    "https://codespeak.net:80/path",
])
def test_canonical_url_path_mappings(url):
    url = DistURL(url)
    path = url.torelpath()
    assert path[0] != "/"
    assert posixpath.normpath(path) == path
    back_url = DistURL.fromrelpath(path)
    assert url == back_url


def test_sorted_by_version():
    l = ["hello-1.3.0.tgz", "hello-1.3.1.tgz", "hello-1.2.9.zip"]
    assert sorted_by_version(l) == \
        ["hello-1.2.9.zip", "hello-1.3.0.tgz", "hello-1.3.1.tgz"]

def test_sorted_by_version_with_attr():
    class A:
        def __init__(self, ver):
            self.ver = ver
        def __eq__(self, other):
            assert self.ver == other.ver
    l = [A("hello-1.2.0.tgz") , A("hello-1.1.0.zip")]
    x = sorted_by_version(l, attr="ver")
    l.reverse()
    assert x == l

def test_guess_pkgname_and_version():
    g = guess_pkgname_and_version
    assert g("hello-1.3.tar.gz") == ("hello", "1.3")
    assert g("hello-1.3") == ("hello", "1.3")
    assert g("hello") == ("hello", "")
