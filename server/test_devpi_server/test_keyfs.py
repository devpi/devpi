import py
import pytest
import os
import stat

from devpi_server.keyfs import KeyFS

@pytest.fixture
def keyfs(gentmp):
    return KeyFS(gentmp())

@pytest.fixture(params=["direct", "a/b/c", ])
def key(request):
    return request.param

class TestKeyFS:

    def test_getempty(self, keyfs):
        assert keyfs._get("somekey", None) is None
        pytest.raises(KeyError, lambda: keyfs._get("somekey"))

    @pytest.mark.parametrize("val", [b"", b"val"])
    def test_get_set_del_exists(self, keyfs, key, val):
        assert not keyfs._exists(key)
        keyfs._set(key, val)
        assert keyfs._exists(key)
        newval = keyfs._get(key)
        assert val == newval
        assert isinstance(newval, type(val))
        assert keyfs._getpath(key).check()
        assert keyfs._delete(key)
        assert not keyfs._delete(key)
        pytest.raises(KeyError, lambda: keyfs._get(key))

    def test_set_twice_on_subdir(self, keyfs):
        keyfs._set("a/b/c", b"value")
        keyfs._set("a/b/c", b"value2")
        assert keyfs._get("a/b/c") == b"value2"

    def test_tempfile(self, keyfs):
        with keyfs.tempfile("abc") as f:
            f.write(b"hello")
        assert os.path.basename(f.name).startswith("abc")
        assert os.path.exists(f.name)
        assert f.key.exists()
        org_stat = stat.S_IMODE(os.stat(f.name).st_mode)
        os.remove(f.name)
        # normal create follows umask
        with open(f.name, "w") as fp:
            fp.write("hello")
        assert org_stat == stat.S_IMODE(os.stat(f.name).st_mode)

    def test_tempfile_movekey(self, keyfs):
        with keyfs.tempfile("abc") as f:
            f.write(b"x")
        key = keyfs.addkey("abc", bytes)
        assert f.key.exists()
        f.key.move(key)
        assert not f.key.exists()

    def test_tempfile_movekey_typemismatch(self, keyfs):
        with keyfs.tempfile("abc") as f:
            f.write(b"x")
        key = keyfs.addkey("abc", int)
        assert f.key.exists()
        with pytest.raises(TypeError):
            f.key.move(key)

    def test_destroyall(self, keyfs):
        keyfs._set("hello/world", b"World")
        keyfs.destroyall()
        assert not keyfs._exists("hello/world")

    def test_getlock(self, keyfs):
        lock1 = keyfs._getlock("hello/world")
        lock2 = keyfs._getlock("hello/world")
        assert lock1 == lock2
        lock1.acquire()
        lock1.acquire(0)


@pytest.mark.parametrize(("type", "val"),
        [(dict, {1:2}),
         (set, set([1,2])),
         (int, 3),
         (tuple, (3,4)),
         (str, "hello")])
class Test_addkey_combinations:
    def test_addkey(self, keyfs, key, type, val):
        attr = keyfs.addkey(key, type)
        assert not attr.exists()
        assert attr.get() == type()
        assert attr.get(val) == val
        assert not attr.exists()
        attr.set(val)
        assert attr.exists()
        assert attr.get() == val
        attr.delete()
        assert not attr.exists()
        assert attr.get() == type()

    def test_addkey_param(self, keyfs, type, val):
        pattr = keyfs.addkey("hello/{some}", type)
        attr = pattr(some="this")
        assert not attr.exists()
        assert attr.get() == type()
        assert attr.get(val) == val
        assert not attr.exists()
        attr.set(val)
        assert attr.exists()
        assert attr.get() == val

        attr2 = pattr(some="that")
        assert not attr2.exists()
        attr.delete()
        assert not attr.exists()
        assert attr.get() == type()

    def test_addkey_unicode(self, keyfs, type, val):
        pattr = keyfs.addkey("hello/{some}", type)
        attr = pattr(some=py.builtin._totext(b'\xe4', "latin1"))
        assert not attr.exists()
        assert attr.get() == type()
        assert attr.get(val) == val
        assert not attr.exists()
        attr.set(val)
        assert attr.exists()
        assert attr.get() == val

class TestKey:
    def test_addkey_type_mismatch(self, keyfs):
        dictkey = keyfs.addkey("some", dict)
        pytest.raises(TypeError, lambda: dictkey.set("hello"))
        dictkey = keyfs.addkey("{that}/some", dict)
        pytest.raises(TypeError, lambda: dictkey(that="t").set("hello"))

    def test_addkey_registered(self, keyfs):
        key1 = keyfs.addkey("some1", dict)
        key2 = keyfs.addkey("some2", list)
        assert len(keyfs.keys) == 2
        assert key1 in keyfs.keys
        assert key2 in keyfs.keys

    def test_addkey_listkeys(self, keyfs):
        key = keyfs.addkey("{name}/some1/{other}", int)
        pytest.raises(KeyError, lambda: key.listnames("name"))
        pytest.raises(KeyError, lambda: key.listnames("other"))
        assert not key.listnames("other", name="this")
        key(name="this", other="1").set(1)
        key(name="this", other="2").set(2)
        key(name="that", other="0").set(1)
        key(name="world", other="0").set(1)
        names = key.listnames("other", name="this")
        assert len(names) == 2
        assert set(names) == set(["1", "2"])

    def test_addkey_listkeys_arbitrary_position(self, keyfs):
        key = keyfs.addkey("{name}/some1/this", int)
        key2 = keyfs.addkey("{name}/some2/this", int)
        names = key.listnames("name")
        assert not names
        key(name="this").set(1)
        key(name="that").set(1)
        key2(name="murg").set(1)
        names = key.listnames("name")
        assert names == set(["this", "that"])

    def test_addkey_listkeys_mismatch(self, keyfs):
        key = keyfs.addkey("{name}/some1/this", int)
        key2 = keyfs.addkey("some/some1", int)
        key2.set(1)
        key(name="x").set(2)
        names = key.listnames("name")
        assert names == set(["x"])



    def test_locked_update(self, keyfs):
        key1 = keyfs.addkey("some1", dict)
        key2 = keyfs.addkey("some2", list)
        with key1.locked_update() as d:
            with key2.locked_update() as l:
                l.append(1)
                d["hello"] = l
        assert key1.get()["hello"] == l

    def test_locked_update_error(self, keyfs):
        key1 = keyfs.addkey("some1", dict)
        key1.set({1:2})
        try:
            with key1.locked_update() as d:
                d["hello"] = "world"
                raise ValueError()
        except ValueError:
            pass
        assert key1.get() == {1:2}

    def test_update(self, keyfs):
        key1 = keyfs.addkey("some1", dict)
        with key1.update() as d:
            d["hello"] = 1
        assert key1.get()["hello"] == 1
        try:
            with key1.update() as d:
                d["hello"] = 2
                raise ValueError()
        except ValueError:
            pass
        assert key1.get()["hello"] == 1


    def test_filestore(self, keyfs):
        key1 = keyfs.addkey("hello", bytes)
        key1.set(b"hello")
        assert key1.get() == b"hello"
        assert key1.filepath.size() == 5

    def test_dirkey(self, keyfs):
        key1 = keyfs.addkey("somedir", "DIR")
        assert key1.filepath.strpath.endswith("somedir")
        assert key1.filepath.strpath.endswith(key1.relpath)
        assert not hasattr(key1, "get")
        assert not hasattr(key1, "set")
        assert not key1.exists()
        key1.filepath.ensure("hello")
        assert key1.exists()
        key1.delete()
        assert not key1.exists()

