import py
import pytest

from devpi_server.keyfs import KeyFS, WriteTransaction, ReadTransaction

@pytest.fixture
def keyfs(gentmp):
    return KeyFS(gentmp())

@pytest.fixture(params=["direct", "a/b/c", ])
def key(request):
    return request.param

class TestKeyFS:

    def test_getempty(self, keyfs):
        pytest.raises(KeyError, lambda: keyfs._get("somekey"))

    @pytest.mark.writetransaction
    @pytest.mark.parametrize("val", [b"", b"val"])
    def test_get_set_del_exists(self, keyfs, key, val):
        k = keyfs.addkey(key, bytes)
        assert not k.exists()
        k.set(val)
        assert k.exists()
        keyfs.restart_as_write_transaction()
        newval = k.get()
        assert val == newval
        assert isinstance(newval, type(val))
        k.delete()
        assert not k.exists()
        keyfs.restart_as_write_transaction()
        assert not k.exists()


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
        keyfs.restart_as_write_transaction()
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
        keyfs.restart_as_write_transaction()
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
        assert not attr.exists()
        keyfs.restart_as_write_transaction()
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
        key1 = keyfs.addkey("some1", dict, "SOME1")
        key2 = keyfs.addkey("some2", list, "SOME2")
        assert len(keyfs._keys) == 2
        assert keyfs._keys["SOME1"] == key1
        assert keyfs._keys["SOME2"] == key2

    def test_update(self, keyfs):
        key1 = keyfs.addkey("some1", dict)
        key2 = keyfs.addkey("some2", list)
        keyfs.restart_as_write_transaction()
        with key1.update() as d:
            with key2.update() as l:
                l.append(1)
                d["hello"] = l
        assert key1.get()["hello"] == l

    def test_get_inplace(self, keyfs):
        key1 = keyfs.addkey("some1", dict)
        keyfs.restart_as_write_transaction()
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
        keyfs.restart_as_write_transaction()
        key1.set(b"hello")
        assert key1.get() == b"hello"
        keyfs.commit_transaction_in_thread()
        assert key1.filepath.size() == 5


@pytest.mark.notransaction
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
    with keyfs.transaction():
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

@pytest.mark.notransaction
class TestTransactionIsolation:
    def test_cannot_write_on_read_trans(self, keyfs):
        tx_1 = ReadTransaction(keyfs)
        assert not hasattr(tx_1, "set")
        assert not hasattr(tx_1, "delete")
        
    def test_serialized_writing(self, keyfs, monkeypatch):
        D = keyfs.addkey("hello", dict)
        tx_1 = WriteTransaction(keyfs)
        class lockity:
            def acquire(self):
                raise ValueError()
        monkeypatch.setattr(keyfs, "_write_lock", lockity())
        with pytest.raises(ValueError):
            WriteTransaction(keyfs)
        monkeypatch.undo()
        tx_2 = ReadTransaction(keyfs)
        tx_1.set(D, {1:1})
        assert tx_2.get(D) == {}
        assert tx_1.get(D) == {1:1}
        tx_1.commit()
        assert tx_2.get(D) == {}

    def test_concurrent_tx_sees_original_value_on_write(self, keyfs):
        D = keyfs.addkey("hello", dict)
        tx_1 = WriteTransaction(keyfs)
        tx_2 = ReadTransaction(keyfs)
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
        tx_1 = WriteTransaction(keyfs)
        tx_2 = ReadTransaction(keyfs)
        tx_1.delete(D)
        tx_1.commit()
        assert tx_2.get(D) == {1:2}

    @pytest.mark.xfail(run=False, reason="no support for concurrent writes")
    def test_concurrent_tx_sees_deleted_while_newer_was_committed(self, keyfs):
        D = keyfs.addkey("hello", dict)
        with keyfs.transaction():
            D.set({1:1})
        with keyfs.transaction():
            D.delete()
        tx_1 = WriteTransaction(keyfs)
        tx_2 = WriteTransaction(keyfs)
        tx_1.set(D, {2:2})
        tx_1.commit()
        assert not tx_2.exists(D)
        tx_3 = WriteTransaction(keyfs)
        assert tx_3.exists(D)

    def test_tx_delete(self, keyfs):
        D = keyfs.addkey("hello", dict)
        with keyfs.transaction():
            D.set({1:1})
        with keyfs.transaction():
            D.delete()
            assert not D.exists()

@pytest.mark.notransaction
def test_bound_history_size(keyfs):
    D = keyfs.addkey("some", dict)
    tx = ReadTransaction(keyfs)
    for i in range(3):
        with keyfs.transaction():
            D.set({i:i})
    with keyfs.transaction():
        assert D.get() == {i:i}

    size = D.filepath.size()
    for i in range(3):
        with keyfs.transaction():
            D.set({i:i})
        assert D.filepath.size() == size
    # let's trigger an exhaustive search
    assert not tx.exists(D)
