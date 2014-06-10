import contextlib
import py
import pytest
from devpi_server.mythread import ThreadPool

from devpi_server.keyfs import KeyFS, WriteTransaction, ReadTransaction, load

notransaction = pytest.mark.notransaction



@pytest.yield_fixture
def keyfs(gentmp, pool):
    keyfs = KeyFS(gentmp())
    pool.register(keyfs.notifier)
    yield keyfs

@pytest.fixture(params=["direct", "a/b/c", ])
def key(request):
    return request.param


class TestKeyFS:
    def test_get_non_existent(self, keyfs):
        key = keyfs.add_key("NAME", "somekey", dict)
        pytest.raises(KeyError, lambda: keyfs.get_value_at(key, 0))

    @pytest.mark.writetransaction
    @pytest.mark.parametrize("val", [b"", b"val"])
    def test_get_set_del_exists(self, keyfs, key, val):
        k = keyfs.add_key("NAME", key, bytes)
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

    def test_no_slashkey(self, keyfs):
        pkey = keyfs.add_key("NAME", "{hello}", dict)
        with pytest.raises(ValueError):
            pkey(hello="this/that")



class TestGetKey:
    def test_typed_keys(self, keyfs):
        key = keyfs.add_key("NAME", "hello", dict)
        assert key == keyfs.get_key("NAME")
        assert key.name == "NAME"

    def test_pattern_key(self, keyfs):
        pkey = keyfs.add_key("NAME", "{hello}/{this}", dict)
        found_key = keyfs.get_key("NAME")
        assert found_key == pkey
        assert pkey.extract_params("cat/dog") == dict(hello="cat", this="dog")
        assert pkey.extract_params("cat") == {}
        assert pkey.name == "NAME"
        key = pkey(hello="cat", this="dog")
        assert key.name == "NAME"


@pytest.mark.parametrize(("type", "val"),
        [(dict, {1:2}),
         (set, set([1,2])),
         (int, 3),
         (tuple, (3,4)),
         (str, "hello")])
class Test_addkey_combinations:
    def test_addkey(self, keyfs, key, type, val):
        attr = keyfs.add_key("NAME", key, type)
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
        pattr = keyfs.add_key("NAME", "hello/{some}", type)
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
        pattr = keyfs.add_key("NAME", "hello/{some}", type)
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
        dictkey = keyfs.add_key("NAME", "some", dict)
        pytest.raises(TypeError, lambda: dictkey.set("hello"))
        dictkey = keyfs.add_key("NAME", "{that}/some", dict)
        pytest.raises(TypeError, lambda: dictkey(that="t").set("hello"))

    def test_addkey_registered(self, keyfs):
        key1 = keyfs.add_key("SOME1", "some1", dict)
        key2 = keyfs.add_key("SOME2", "some2", list)
        assert len(keyfs._keys) == 2
        assert keyfs.get_key("SOME1") == key1
        assert keyfs.get_key("SOME2") == key2

    def test_update(self, keyfs):
        key1 = keyfs.add_key("NAME", "some1", dict)
        key2 = keyfs.add_key("NAME", "some2", list)
        keyfs.restart_as_write_transaction()
        with key1.update() as d:
            with key2.update() as l:
                l.append(1)
                d["hello"] = l
        assert key1.get()["hello"] == l

    def test_get_inplace(self, keyfs):
        key1 = keyfs.add_key("NAME", "some1", dict)
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
        key1 = keyfs.add_key("NAME", "hello", bytes)
        keyfs.restart_as_write_transaction()
        key1.set(b"hello")
        assert key1.get() == b"hello"
        keyfs.commit_transaction_in_thread()


@notransaction
@pytest.mark.parametrize(("type", "val"),
        [(dict, {1:2}),
         (set, set([1,2])),
         (int, 3),
         (tuple, (3,4)),
         (str, "hello")])
def test_trans_get_not_modify(keyfs, type, val, monkeypatch):
    attr = keyfs.add_key("NAME", "hello", type)
    with keyfs.transaction():
        attr.set(val)
    with keyfs.transaction():
        assert attr.get() == val
    # make sure keyfs doesn't write during the transaction and its commit
    orig_write = py.path.local.write
    def write_checker(path, content):
        assert not path.endswith(attr.relpath)
        orig_write(path, content)
    monkeypatch.setattr(py.path.local, "write", write_checker)
    with keyfs.transaction():
        x = attr.get()
    assert x == val

@notransaction
class TestTransactionIsolation:
    def test_cannot_write_on_read_trans(self, keyfs):
        tx_1 = ReadTransaction(keyfs)
        assert not hasattr(tx_1, "set")
        assert not hasattr(tx_1, "delete")

    def test_serialized_writing(self, keyfs, monkeypatch):
        D = keyfs.add_key("NAME", "hello", dict)
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
        D = keyfs.add_key("NAME", "hello", dict)
        tx_1 = WriteTransaction(keyfs)
        tx_2 = ReadTransaction(keyfs)
        ser = keyfs._fs.next_serial
        tx_1.set(D, {1:1})
        tx1_serial = tx_1.commit()
        assert tx1_serial == ser
        assert keyfs._fs.next_serial == ser + 1
        assert tx_2.at_serial == ser - 1
        assert D not in tx_2.cache and D not in tx_2.dirty
        assert tx_2.get(D) == {}

    def test_concurrent_tx_sees_original_value_on_delete(self, keyfs):
        D = keyfs.add_key("NAME", "hello", dict)
        with keyfs.transaction():
            D.set({1:2})
        tx_1 = WriteTransaction(keyfs)
        tx_2 = ReadTransaction(keyfs)
        tx_1.delete(D)
        tx_1.commit()
        assert tx_2.get(D) == {1:2}

    @pytest.mark.xfail(run=False, reason="no support for concurrent writes")
    def test_concurrent_tx_sees_deleted_while_newer_was_committed(self, keyfs):
        D = keyfs.add_key("NAME", "hello", dict)
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
        D = keyfs.add_key("NAME", "hello", dict)
        with keyfs.transaction():
            D.set({1:1})
        with keyfs.transaction():
            D.delete()
            assert not D.exists()

    def test_import_changelog_entry(self, keyfs, tmpdir):
        D = keyfs.add_key("NAME", "hello", dict)
        with keyfs.transaction(write=True):
            D.set({1:1})
        with keyfs.transaction(write=True):
            D.delete()
        with keyfs.transaction(write=True):
            D.set({2:2})
        serial = keyfs._fs.next_serial - 1
        assert serial == 2
        # load entries into new keyfs instance
        new_keyfs = KeyFS(tmpdir.join("newkeyfs"))
        D2 = new_keyfs.add_key("NAME", "hello", dict)
        for serial in range(3):
            raw_entry = keyfs._fs.get_raw_changelog_entry(serial)
            entry = load(py.io.BytesIO(raw_entry))
            new_keyfs.import_changelog_entry(serial, entry)
        assert new_keyfs.get_value_at(D2, 0) == {1:1}
        with pytest.raises(KeyError):
            assert new_keyfs.get_value_at(D2, 1)
        assert new_keyfs.get_value_at(D2, 2) == {2:2}

@notransaction
class TestDeriveKey:
    def test_direct_from_file(self, keyfs):
        D = keyfs.add_key("NAME", "hello", dict)
        with keyfs.transaction(write=True):
            D.set({1:1})
        key = keyfs.derive_key(D.relpath)
        assert key == D
        assert key.params == {}

    def test_pattern_from_file(self, keyfs):
        pkey = keyfs.add_key("NAME", "{name}/{index}", dict)
        params = dict(name="hello", index="world")
        D = pkey(**params)
        with keyfs.transaction(write=True):
            D.set({1:1})
        assert not hasattr(keyfs, "tx")
        key = keyfs.derive_key(D.relpath)
        assert key == D
        assert key.params == params

    def test_direct_not_committed(self, keyfs):
        D = keyfs.add_key("NAME", "hello", dict)
        with keyfs.transaction(write=True):
            D.set({})
            key = keyfs.derive_key(D.relpath)
            assert key == D
            assert key.params == {}

    def test_pattern_not_committed(self, keyfs):
        pkey = keyfs.add_key("NAME", "{name}/{index}", dict)
        params = dict(name="hello", index="world")
        D = pkey(**params)
        with keyfs.transaction(write=True):
            D.set({})
            key = keyfs.derive_key(D.relpath)
            assert key == D
            assert key.params == params



@notransaction
class TestSubscriber:
    def test_change_subscription(self, keyfs, queue, pool):
        key1 = keyfs.add_key("NAME1", "hello", int)
        keyfs.notifier.on_key_change(key1, queue.put)
        pool.start()
        with keyfs.transaction():
            key1.set(1)
            assert queue.empty()
        event = queue.get()
        assert event.value == 1
        assert event.typedkey == key1
        assert event.at_serial == 0
        assert event.back_serial == -1

    def test_change_subscription_fails(self, keyfs, queue, pool):
        key1 = keyfs.add_key("NAME1", "hello", int)
        def failing(event):
            queue.put("willfail")
            0/0
        keyfs.notifier.on_key_change(key1, failing)
        keyfs.notifier.on_key_change(key1, queue.put)
        pool.start()
        with keyfs.transaction():
            key1.set(1)
            assert queue.empty()
        msg = queue.get()
        assert msg == "willfail"
        event = queue.get()
        assert event.typedkey == key1

    def test_persistent(self, tmpdir, queue, monkeypatch):
        @contextlib.contextmanager
        def make_keyfs():
            keyfs = KeyFS(tmpdir)
            key1 = keyfs.add_key("NAME1", "hello", int)
            keyfs.notifier.on_key_change(key1, queue.put)
            pool = ThreadPool()
            pool.register(keyfs.notifier)
            pool.start()
            try:
                yield key1
            finally:
                pool.shutdown()

        with make_keyfs() as key1:
            keyfs = key1.keyfs
            monkeypatch.setattr(keyfs._fs, "_notify_on_transaction",
                                lambda x: 0/0)
            # we prevent the hooks from getting called
            with pytest.raises(ZeroDivisionError):
                with keyfs.transaction():
                    key1.set(1)
            assert keyfs.get_next_serial() == 1
            assert keyfs.notifier.read_event_serial() == 0
        # and then we restart keyfs and see if the hook still gets called
        monkeypatch.undo()
        with make_keyfs() as key1:
            event = queue.get()
        assert event.typedkey == key1
        assert key1.keyfs.notifier.read_event_serial() == 1

    def test_subscribe_pattern_key(self, keyfs, queue, pool):
        pkey = keyfs.add_key("NAME1", "{name}", int)
        keyfs.notifier.on_key_change(pkey, queue.put)
        key = pkey(name="hello")
        pool.start()
        with keyfs.transaction():
            key.set(1)
        ev = queue.get()
        assert ev.typedkey == key
        assert ev.typedkey.params == {"name": "hello"}
        assert ev.typedkey.name == pkey.name

    def test_wait_for_event(self, keyfs, pool):
        pkey = keyfs.add_key("NAME1", "{name}", int)
        key = pkey(name="hello")
        pool.start()
        for i in range(10):
            with keyfs.transaction():
                key.set(1)
        keyfs.notifier.wait_for_event_serial(9)



