import pytest
import posixpath
from devpi.util.url import *
import os.path

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

#def test_joinpath_justpath():
#    import posixpath
#    p = posixpath.join("/hello", "world/")
#    assert p == "/hello/world/"
#
#    p = posixpath.join("hello", "world/")
#    assert p == "hello/world/"

def test_getnetloc():
    assert getnetloc("http://hello.com") == "hello.com"
    assert getnetloc("http://hello.com:80") == "hello.com"
    assert getnetloc("http://hello.com:807") == "hello.com:807"
    assert getnetloc("http://hello.com:807", True) == "http://hello.com:807"
    assert getnetloc("https://hello.com:807", True) == "https://hello.com:807"

def test_getpath():
    assert getpath("https://hello.com:807") == ""
    assert getpath("https://hello.com:807/hello") == "/hello"


#
# test url2path/path2url
#
from devpi.util.url import url2path, path2url

@pytest.mark.parametrize("url", [
    "http://codespeak.net", "https://codespeak.net",
    "http://codespeak.net/path",
    "http://codespeak.net:3123/path",
    "https://codespeak.net:80/path",
])
def test_canonical_url_path_mappings(url):
    path = url2path(url)
    assert path[0] != "/"
    assert posixpath.normpath(path) == path
    back_url = path2url(path)
    assert url == back_url


def test_getscheme():
    assert getscheme("http://hello") == "http"
    assert getscheme("whatever://hello") == "whatever"



def test_ishttp():
    assert ishttp("http://hello/path")
    assert ishttp("http://hello")
    assert ishttp("https://hello")
    assert not ishttp("http://")
    assert not ishttp("ssh://")
    assert not ishttp("http:")



def test_parselinks():
    content = """<html><a href="href" rel="rel">text</a></html>"""
    link = parselinks(content)[0]
    assert link.href == "href"
    assert "rel" in link.rel
    assert link.text == "text"

def test_parselinks_norel_notext():
    content = """<html><a href="href" ></a></html>"""
    link = parselinks(content)[0]
    assert link.href == "href"
    assert link.rel == []
    assert link.text == ""

def test_parselinks_tworel():
    content = """<html><a href="href" rel="homepage download"></a></html>"""
    link = parselinks(content)[0]
    assert link.href == "href"
    assert "homepage" in link.rel
    assert "download" in link.rel
    assert link.text == ""


def test_is_valid_url():
    assert is_valid_url("http://heise.de")
    assert is_valid_url("http://heise.de:80")
    assert is_valid_url("https://heise.de/hello")
    assert not is_valid_url("ftp://heise.de/hello")
    assert not is_valid_url("http://heise.de:")

