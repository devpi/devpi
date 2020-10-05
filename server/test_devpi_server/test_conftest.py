import py
import pytest


def test_gentmp_suffix_raises(gentmp):
    t = gentmp("source")
    assert not t.listdir()
    pytest.raises(py.error.EEXIST, lambda: gentmp("source"))


def test_gentmp_suffix(gentmp):
    source = gentmp("source")
    dest = gentmp("dest")
    assert source.dirpath() == dest.dirpath()
    assert source.basename.startswith("source")
    assert dest.basename.startswith("dest")


def test_gentmp_unique(gentmp):
    s1 = gentmp()
    s2 = gentmp()
    assert s1 != s2
    assert s1.dirpath() == s2.dirpath()


def test_makexom(makexom, maketestapp):
    xom1 = makexom()
    xom2 = makexom()
    assert xom1.config.serverdir != xom2.config.serverdir
    testapp1 = maketestapp(xom1)
    testapp1.get("/")
    testapp2 = maketestapp(xom2)
    testapp2.get("/")


def test_makemapp(makemapp):
    mapp1 = makemapp()
    mapp1.create_user("hello", "password")
    assert "hello" in mapp1.getuserlist()
    mapp2 = makemapp()
    assert "hello" not in mapp2.getuserlist()
    assert mapp1.xom.config.serverdir != mapp2.xom.config.serverdir
