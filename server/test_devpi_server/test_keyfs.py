import py
import pytest
import os
import stat
import threading

from devpi_server.keyfs import KeyFS, Transaction

@pytest.fixture
def keyfs(gentmp):
    return KeyFS(gentmp())

@pytest.fixture(params=["direct", "a/b/c", ])
def key(request):
    return request.param

class TestKeyFS:

    def test_getempty(self, keyfs):
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
        assert not key.exists()
        with keyfs.transaction():
            f.key.move(key)
        assert not f.key.exists()

    @pytest.mark.notransaction
    def test_move_visibility_in_transaction(self, keyfs, monkeypatch):
        with keyfs.tempfile("abc") as f:
            f.write(b"x")
        key = keyfs.addkey("123", bytes)
        assert f.key.exists()
        assert not key.exists()
        monkeypatch.setattr("os.rename", None)
        with keyfs.transaction():
            f.key.move(key)
            # within the transaction the moved key exists
            assert key.exists()
            # but not on the file system yet
            assert not key.filepath.exists()
            monkeypatch.undo()  # so that transaction commit works
        assert key.exists()
        assert key.filepath.exists()

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
        assert not attr.exists()
        with keyfs.transaction():
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
        assert not attr.exists()
        with keyfs.transaction():
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
        with keyfs.transaction():
            assert not attr.exists()
            assert attr.get() == type()
            assert not attr.exists()
            attr.set(val)
            assert attr.exists()
            assert attr.get() == val

class TestKey:
    def test_addkey_type_mismatch(self, keyfs):
        dictkey = keyfs.addkey("some", dict)
        with keyfs.transaction():
            pytest.raises(TypeError, lambda: dictkey.set("hello"))
            dictkey = keyfs.addkey("{that}/some", dict)
            pytest.raises(TypeError, lambda: dictkey(that="t").set("hello"))

    def test_addkey_registered(self, keyfs):
        key1 = keyfs.addkey("some1", dict, "SOME1")
        key2 = keyfs.addkey("some2", list, "SOME2")
        assert len(keyfs._keys) == 2
        assert keyfs._keys["SOME1"] == key1
        assert keyfs._keys["SOME2"] == key2

    def test_update(self, keyfs):
        key1 = keyfs.addkey("some1", dict)
        key2 = keyfs.addkey("some2", list)
        with keyfs.transaction():
            with key1.update() as d:
                with key2.update() as l:
                    l.append(1)
                    d["hello"] = l
            assert key1.get()["hello"] == l

    def test_get_inplace(self, keyfs):
        key1 = keyfs.addkey("some1", dict)
        with keyfs.transaction():
            key1.set({1:2})
            try:
                with key1.update() as d:
                    d["hello"] = "world"
                    raise ValueError()
            except ValueError:
                pass
            assert key1.get() == {1:2, "hello": "world"}

    def test_filestore(self, keyfs):
        key1 = keyfs.addkey("hello", bytes)
        with keyfs.transaction():
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


@pytest.mark.parametrize(("type", "val"),
        [(dict, {1:2}),
         (set, set([1,2])),
         (int, 3),
         (tuple, (3,4)),
         (str, "hello")])
def test_trans_get_not_modify(keyfs, type, val, monkeypatch):
    attr = keyfs.addkey("hello", type)
    with keyfs.transaction():
        attr.set(val)
    assert attr.get() == val
    # make sure keyfs doesn't write during the transaction and its commit
    orig_write = py.path.local.write
    def write_checker(path, content):
        assert path != attr.filepath
        orig_write(path, content)
    monkeypatch.setattr(py.path.local, "write", write_checker)
    with keyfs.transaction():
        x = attr.get()
    assert x == val 

class TestTransactionIsolation:
    def test_latest_writer_wins(self, keyfs):
        D = keyfs.addkey("hello", dict)
        tx_1 = Transaction(keyfs)
        tx_2 = Transaction(keyfs)
        tx_1.set(D, {1:1})
        assert tx_2.get(D) == {}
        tx_2.set(D, {2:2})
        assert tx_1.get(D) == {1:1}
        assert tx_2.get(D) == {2:2}
        tx_1.commit()
        assert tx_2.get(D) == {2:2}
        tx_2.commit()
        assert D.get() == {2:2}

    def test_concurrent_tx_sees_original_value_on_write(self, keyfs):
        D = keyfs.addkey("hello", dict)
        tx_1 = Transaction(keyfs)
        tx_2 = Transaction(keyfs)
        ser = keyfs._fs.current_serial
        tx_1.set(D, {1:1})
        tx_1.commit()
        assert keyfs._fs.current_serial == ser + 1
        assert tx_2.from_serial == ser
        assert D not in tx_2.cache and D not in tx_2.dirty
        assert tx_2.get(D) == {}

    def test_concurrent_tx_sees_original_value_on_delete(self, keyfs):
        D = keyfs.addkey("hello", dict)
        with keyfs.transaction():
            D.set({1:2})
        tx_1 = Transaction(keyfs)
        tx_2 = Transaction(keyfs)
        tx_1.delete(D)
        tx_1.commit()
        assert tx_2.get(D) == {1:2}

    def test_concurrent_tx_sees_deleted_while_newer_was_committed(self, keyfs):
        D = keyfs.addkey("hello", dict)
        with keyfs.transaction():
            D.set({1:1})
        with keyfs.transaction():
            D.delete()
        tx_1 = Transaction(keyfs)
        tx_2 = Transaction(keyfs)
        tx_1.set(D, {2:2})
        tx_1.commit()
        assert not tx_2.exists(D)
        tx_3 = Transaction(keyfs)
        assert tx_3.exists(D)

    def test_tx_delete(self, keyfs):
        D = keyfs.addkey("hello", dict)
        with keyfs.transaction():
            D.set({1:1})
        with keyfs.transaction():
            D.delete()
            assert not D.exists()
