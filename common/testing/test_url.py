import pytest
from devpi_common.url import *

class TestURL:
    def test_basename(self):
        d = URL("http://codespeak.net/basename")
        assert d.basename == "basename"
        d = URL("http://codespeak.net")
        assert not d.basename

    def test_repr(self):
        d = URL("http://host.com/path")
        assert repr(d) == "<URL url='http://host.com/path'>"


    def test_parentbasename(self):
        d = URL("http://codespeak.net/simple/basename/")
        assert d.parentbasename == "basename"
        assert d.basename == ""

    def test_hashing(self):
        assert hash(URL("http://a")) == hash(URL("http://a"))
        assert URL("http://a") == URL("http://a")

    def test_eggfragment(self):
        url = URL("http://a/py.tar.gz#egg=py-dev")
        assert url.eggfragment == "py-dev"

    def test_md5(self):
        url = URL("http://a/py.tar.gz#md5=123123")
        assert url.md5 == "123123"

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
        d_url = URL(url)
        url_joined = d_url.joinpath(path).url
        assert url_joined == expected
        assert URL(url, path).url == expected

        assert d_url.joinpath(path, "end").url == expected + "/end"
        assert URL(url, path, "end").url == expected + "/end"

        assert d_url.joinpath(path, "end", asdir=1).url == expected + "/end/"
        assert URL(url, path, "end", asdir=1).url == expected + "/end/"

    def test_addpath(self):
        url = URL("http://root.com/path")
        assert url.addpath("sub").url == "http://root.com/path/sub"
        assert url.addpath("sub", asdir=1).url == "http://root.com/path/sub/"
        url = URL("http://root.com/path/")
        assert url.addpath("sub").url == "http://root.com/path/sub"
        assert url.addpath("sub", asdir=1).url == "http://root.com/path/sub/"

    def test_instantiate_with_url(self):
        url = URL("http://hesie.de")
        assert URL(url) == url

    def test_empty_url(self):
        assert not URL("")
        assert not URL()

    def test_asdir(self):
        assert URL("http://heise.de").asdir().url == "http://heise.de/"
        assert URL("http://py.org/path").asdir().url == "http://py.org/path/"
        assert URL("http://py.org/path/").asdir().url == "http://py.org/path/"

    def test_asfile(self):
        assert URL("http://heise.de").asfile().url == "http://heise.de"
        assert URL("http://heise.de/").asfile().url == "http://heise.de"
        assert URL("http://x.de/path/").asfile().url == "http://x.de/path"
        assert URL("http://x.de/path").asfile().url == "http://x.de/path"

    def test_joinpath_asdir(self):
        url = URL("http://heise.de")
        new = url.joinpath("hello", asdir=1)
        assert new.url == "http://heise.de/hello/"
        new = url.joinpath("hello/", asdir=1)
        assert new.url == "http://heise.de/hello/"

    def test_geturl_nofrag(self):
        url = URL("http://a/py.tar.gz#egg=py-dev")
        assert url.geturl_nofragment() == "http://a/py.tar.gz"

    def test_url_nofrag(self):
        url = URL("http://a/py.tar.gz#egg=py-dev")
        res = url.url_nofrag
        assert not isinstance(res, URL)
        assert res == "http://a/py.tar.gz"

    @pytest.mark.parametrize("url,path,expected", [
        ("/something/this", "/something/that", "that"),
        ("/something/this", "/something/that/", "that/"),
        ("/something/this", "/something/this", "this"),
        ("/something/this", "/something/this/", "this/"),
        ("/something/this", "/", "../"),
        ("/", "/this/that/", "this/that/"),
        ("/something/this/", "/something/that", "../that"),
        ("/something/this/", "/other/that", "../../other/that"),
        ("/something/this/", "/other/that", "../../other/that"),
        ("/something/this/", "/something/this/that", "that"),
        ("/something/this/", "/something/this/that/there", "that/there"),
    ])
    def test_relpath(self, url, path, expected):
        url = URL("http://example.com" + url)
        relpath = url.relpath(path)
        assert relpath == expected

    def test_relpath_edge_case(self):
        with pytest.raises(ValueError):
            URL("http://qwe/path").relpath("lkjqwe")

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
    url = URL(url)
    path = url.torelpath()
    assert path[0] != "/"
    assert posixpath.normpath(path) == path
    back_url = URL.fromrelpath(path)
    assert url == back_url

