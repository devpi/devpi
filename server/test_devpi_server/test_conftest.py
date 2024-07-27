import pytest


def test_gen_path_suffix_raises(gen_path):
    t = gen_path("source")
    assert not list(t.iterdir())
    pytest.raises(FileExistsError, lambda: gen_path("source"))


def test_gen_path_suffix(gen_path):
    source = gen_path("source")
    dest = gen_path("dest")
    assert source.parent == dest.parent
    assert source.name.startswith("source")
    assert dest.name.startswith("dest")


def test_gen_path_unique(gen_path):
    s1 = gen_path()
    s2 = gen_path()
    assert s1 != s2
    assert s1.parent == s2.parent


def test_gentmp_suffix_raises(gentmp):
    import py
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
    assert xom1.config.server_path != xom2.config.server_path
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
    assert mapp1.xom.config.server_path != mapp2.xom.config.server_path
