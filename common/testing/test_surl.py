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

    def test_versionapi(self):
        url = DistURL("http://a/py-1.0.tar.gz")
        assert url.pkgname_and_version == ("py", "1.0")
        url = DistURL("http://a/py_some-1.0.tar.gz")
        assert url.pkgname_and_version == ("py_some", "1.0")

    def test_easyversion_comparison(self):
        url1 = DistURL("http://a/py-1.0.tar.gz")
        url2 = DistURL("http://a/py-1.0.dev1.tar.gz")
        url3 = DistURL("http://a/py.zip#egg=py-dev")
        assert url3.easyversion > url1.easyversion > url2.easyversion
        assert url3 > url1 > url2

@pytest.mark.parametrize(("releasename", "expected"), [
    ("pytest-2.3.4.zip", ("pytest", "2.3.4", ".zip")),
    ("pytest-2.3.4-py27.egg", ("pytest", "2.3.4", "-py27.egg")),
    ("dddttt-0.1.dev38-py2.7.egg", ("dddttt", "0.1.dev38", "-py2.7.egg")),
    ("devpi-0.9.5.dev1-cp26-none-linux_x86_64.whl",
        ("devpi", "0.9.5.dev1", "-cp26-none-linux_x86_64.whl")),
    ("wheel-0.21.0-py2.py3-none-any.whl", ("wheel", "0.21.0", "-py2.py3-none-any.whl")),
    ("green-0.4.0-py2.5-win32.egg", ("green", "0.4.0", "-py2.5-win32.egg")),
    ("Candela-0.2.1.macosx-10.4-x86_64.exe", ("Candela", "0.2.1",
                                             ".macosx-10.4-x86_64.exe")),
    ("Cambiatuscromos-0.1.1alpha.linux-x86_64.exe",
        ("Cambiatuscromos", "0.1.1alpha", ".linux-x86_64.exe")),
    ("Aesthete-0.4.2.win32.exe", ("Aesthete", "0.4.2", ".win32.exe")),
    ("DTL-1.0.5.win-amd64.exe", ("DTL", "1.0.5", ".win-amd64.exe")),
    ("Cheetah-2.2.2-1.x86_64.rpm", ("Cheetah", "2.2.2-1", ".x86_64.rpm")),
    ("Cheetah-2.2.2-1.src.rpm", ("Cheetah", "2.2.2-1", ".src.rpm")),
    ("Cheetah-2.2.2-1.x85.rpm", ("Cheetah", "2.2.2-1", ".x85.rpm")),
    ("Cheetah-2.2.2.dev1.x85.rpm", ("Cheetah", "2.2.2.dev1", ".x85.rpm")),
    ("Cheetah-2.2.2.dev1.noarch.rpm", ("Cheetah", "2.2.2.dev1", ".noarch.rpm")),
    ("deferargs.tar.gz", ("deferargs", "", ".tar.gz")),
    ("Twisted-12.0.0.win32-py2.7.msi",
        ("Twisted", "12.0.0", ".win32-py2.7.msi")),
])
def test_splitbasename(releasename, expected):
    result = splitbasename(releasename)
    assert result == expected
    #assert DistURL("http://hello/%s" % releasename).splitbasename() == expected

@pytest.mark.parametrize(("releasename", "expected"), [
    ("x-2.3.zip", ("source", "sdist")),
    ("x-2.3-0.4.0.win32-py3.1.exe", ("3.1", "bdist_wininst")),
    ("x-2.3-py27.egg", ("2.7", "bdist_egg")),
    ("wheel-0.21.0-py2.py3-none-any.whl", ("2.7", "bdist_wheel")),
    ("devpi-0.9.5.dev1-cp26-none-linux_x86_64.whl", ("2.6", "bdist_wheel")),
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

def test_version():
    ver1 = Version("1.0")
    ver2 = Version("1.1")
    assert max([ver1, ver2]) == ver2
