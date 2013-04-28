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
    ("green-0.4.0-py2.5-win32.egg", ("green", "0.4.0", "-py2.5-win32.egg")),
])
def test_splitting(releasename, expected):
    result = splitbasename(releasename)
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
    assert os.path.normpath(path) == path
    back_url = DistURL.fromrelpath(path)
    assert url == back_url

