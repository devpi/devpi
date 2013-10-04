import pytest
import posixpath
from devpi_common.c_url import *
import os.path

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
    link = parselinks(content, "http://root")[0]
    assert link.url == "http://root/href"

def test_is_valid_url():
    assert is_valid_url("http://heise.de")
    assert is_valid_url("http://heise.de:80")
    assert is_valid_url("https://heise.de/hello")
    assert not is_valid_url("ftp://heise.de/hello")
    assert not is_valid_url("http://heise.de:")

