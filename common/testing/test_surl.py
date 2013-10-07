import pytest
from devpi_common.s_url import *

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

    @pytest.mark.parametrize("url,path,expected", [
        ("http://root", "dir1", "http://root/dir1"),
        ("http://root", "dir1/", "http://root/dir1/"),
        ("http://root/", "dir1/", "http://root/dir1/"),
        ("http://root/dir1", "dir2", "http://root/dir2"),
        ("http://root/dir1/", "dir2/", "http://root/dir1/dir2/"),
        ("http://root/dir1/", "/dir2", "http://root/dir2"),
        ("http://root/dir1/", "/dir2/", "http://root/dir2/"),
    ])
    def test_joinpath(self, url, path, expected):
        d_url = DistURL(url)
        url_joined = d_url.joinpath(path).url
        assert url_joined == expected
        assert DistURL(url, path).url == expected

        assert d_url.joinpath(path, "end").url == expected + "/end"
        assert DistURL(url, path, "end").url == expected + "/end"

        assert d_url.joinpath(path, "end", asdir=1).url == expected + "/end/"
        assert DistURL(url, path, "end", asdir=1).url == expected + "/end/"

    def test_joinpath_asdir(self):
        url = DistURL("http://heise.de")
        new = url.joinpath("hello", asdir=1)
        assert new.url == "http://heise.de/hello/"
        new = url.joinpath("hello/", asdir=1)
        assert new.url == "http://heise.de/hello/"

    def test_geturl_nofrag(self):
        url = DistURL("http://a/py.tar.gz#egg=py-dev")
        assert url.geturl_nofragment() == "http://a/py.tar.gz"

    def test_url_nofrag(self):
        url = DistURL("http://a/py.tar.gz#egg=py-dev")
        res = url.url_nofrag
        assert not isinstance(res, DistURL)
        assert res == "http://a/py.tar.gz"


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

