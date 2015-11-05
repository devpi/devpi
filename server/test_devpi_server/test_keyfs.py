import contextlib
import py
import pytest
from devpi_server.mythread import ThreadPool

from devpi_server.keyfs import *  # noqa

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

    @notransaction
    def test_keyfs_readonly(self, tmpdir):
        keyfs = KeyFS(tmpdir, readonly=True)
        with pytest.raises(keyfs.ReadOnly):
            with keyfs.transaction(write=True):
                pass
        assert not hasattr(keyfs, "tx")
        with pytest.raises(keyfs.ReadOnly):
            with keyfs.transaction():
                keyfs.restart_as_write_transaction()
        with pytest.raises(keyfs.ReadOnly):
            keyfs.begin_transaction_in_thread(write=True)
        with keyfs.transaction():
            pass

    @pytest.mark.writetransaction
    @pytest.mark.parametrize("val", [b"", b"val"])
    def test_get_set_del_exists(self, keyfs, key, val):
        k = keyfs.add_key("NAME", key, bytes)
        assert not k.exists()
        k.set(val)
        assert k.exists()
        newval = k.get()
        assert val == newval
        assert isinstance(newval, type(val))
        k.delete()
        assert not k.exists()
        keyfs.commit_transaction_in_thread()
        with keyfs.transaction():
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

    def test_readonly(self, keyfs):
        key1 = keyfs.add_key("NAME", "some1", dict)
        keyfs.restart_as_write_transaction()
        with key1.update() as d:
            d[1] = l = [1,2,3]
        assert key1.get()[1] == l
        keyfs.commit_transaction_in_thread()
        with keyfs.transaction(write=False):
            assert key1.get()[1] == l
            with pytest.raises(TypeError):
                key1.get()[13] = "something"

    def test_write_then_readonly(self, keyfs):
        key1 = keyfs.add_key("NAME", "some1", dict)
        keyfs.restart_as_write_transaction()
        with key1.update() as d:
            d[1] = [1,2,3]

        # if we get it new, we still get a readonly view
        assert is_deeply_readonly(key1.get())

        # if we get it new in write mode, we get a new copy
        d2 = key1.get(readonly=False)
        assert d2 == d
        d2[3] = 4
        assert d2 != d

    def test_update(self, keyfs):
        key1 = keyfs.add_key("NAME", "some1", dict)
        key2 = keyfs.add_key("NAME", "some2", list)
        keyfs.restart_as_write_transaction()
        with key1.update() as d:
            with key2.update() as l:
                l.append(1)
                d[py.builtin._totext("hello")] = l
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
        assert key1.get() == {1:2}  # , "hello": "world"}

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
    with keyfs.transaction(write=True):
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
        key = keyfs.add_key("hello", "hello", dict)
        tx_1 = Transaction(keyfs)
        with pytest.raises(AssertionError):
            tx_1.set(key, {})
        with pytest.raises(AssertionError):
            tx_1.delete(key)

    def test_serialized_writing(self, keyfs, monkeypatch):
        D = keyfs.add_key("NAME", "hello", dict)
        tx_1 = Transaction(keyfs, write=True)
        class lockity:
            def acquire(self):
                raise ValueError()
        monkeypatch.setattr(keyfs, "_write_lock", lockity())
        with pytest.raises(ValueError):
            Transaction(keyfs, write=True)
        monkeypatch.undo()
        tx_2 = Transaction(keyfs)
        tx_1.set(D, {1:1})
        assert tx_2.get(D) == {}
        assert tx_1.get(D) == {1:1}
        tx_1.commit()
        assert tx_2.get(D) == {}

    def test_concurrent_tx_sees_original_value_on_write(self, keyfs):
        D = keyfs.add_key("NAME", "hello", dict)
        tx_1 = Transaction(keyfs, write=True)
        tx_2 = Transaction(keyfs)
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
        with keyfs.transaction(write=True):
            D.set({1:2})
        tx_1 = Transaction(keyfs, write=True)
        tx_2 = Transaction(keyfs)
        tx_1.delete(D)
        tx_1.commit()
        assert tx_2.get(D) == {1:2}

    def test_not_exist_yields_readonly(self, keyfs):
        D = keyfs.add_key("NAME", "hello", dict)
        with keyfs.transaction():
            x = D.get()
        assert x == {}
        with pytest.raises(TypeError):
            x[1] = 3

    def test_tx_delete(self, keyfs):
        D = keyfs.add_key("NAME", "hello", dict)
        with keyfs.transaction(write=True):
            D.set({1:1})
        with keyfs.transaction(write=True):
            D.delete()
            assert not D.exists()

    def test_import_changes(self, keyfs, tmpdir):
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
            changes = keyfs._fs.get_changes(serial)
            new_keyfs.import_changes(serial, changes)
        assert new_keyfs.get_value_at(D2, 0) == {1:1}
        with pytest.raises(KeyError):
            assert new_keyfs.get_value_at(D2, 1)
        assert new_keyfs.get_value_at(D2, 2) == {2:2}

    def test_get_value_at_modify_inplace_is_safe(self, keyfs):
        from copy import deepcopy
        D = keyfs.add_key("NAME", "hello", dict)
        d = {1: set(), 2: dict(), 3: []}
        d_orig = deepcopy(d)
        with keyfs.transaction(write=True):
            D.set(d)
        assert keyfs.get_value_at(D, 0) == d_orig
        d2 = keyfs.get_value_at(D, 0)
        with pytest.raises(AttributeError):
            d2[1].add(4)
        with pytest.raises(TypeError):
            d2[2][3] = 5
        with pytest.raises(AttributeError):
            d2[3].append(6)
        assert keyfs.get_value_at(D, 0) == d_orig

    def test_is_dirty(self, keyfs):
        D = keyfs.add_key("NAME", "hello", dict)
        with keyfs.transaction():
            assert not D.is_dirty()
        with keyfs.transaction(write=True):
            assert not D.is_dirty()
            D.set({1:1})
            assert D.is_dirty()
        with keyfs.transaction(write=True):
            assert not D.is_dirty()

    def future_maybe_test_bounded_cache(self, keyfs):  # if we ever introduce it
        import random
        D = keyfs.add_key("NAME", "hello", dict)
        size = keyfs._fs.CHANGELOG_CACHE_SIZE
        for i in range(size * 3):
            with keyfs.transaction(write=True):
                D.set({i:i})
            with keyfs.transaction():
                D.get()
            assert len(keyfs._fs._changelog_cache) <= \
                   keyfs._fs.CHANGELOG_CACHE_SIZE + 1

        for i in range(size * 2):
            j = random.randrange(0, size * 3)
            keyfs.get_value_at(D, j)
            assert len(keyfs._fs._changelog_cache) <= \
                   keyfs._fs.CHANGELOG_CACHE_SIZE + 1

    def test_import_changes_subscriber(self, keyfs, tmpdir):
        pkey = keyfs.add_key("NAME", "hello/{name}", dict)
        D = pkey(name="world")
        with keyfs.transaction(write=True):
            D.set({1:1})
        assert keyfs.get_current_serial() == 0
        # load entries into new keyfs instance
        new_keyfs = KeyFS(tmpdir.join("newkeyfs"))
        pkey = new_keyfs.add_key("NAME", "hello/{name}", dict)
        l = []
        new_keyfs.subscribe_on_import(pkey, lambda *args: l.append(args))
        changes = keyfs._fs.get_changes(0)
        new_keyfs.import_changes(0, changes)
        assert l[0][1:] == (new_keyfs.NAME(name="world"), {1:1}, -1)

    def test_import_changes_subscriber_error(self, keyfs, tmpdir):
        pkey = keyfs.add_key("NAME", "hello/{name}", dict)
        D = pkey(name="world")
        with keyfs.transaction(write=True):
            D.set({1:1})
        new_keyfs = KeyFS(tmpdir.join("newkeyfs"))
        pkey = new_keyfs.add_key("NAME", "hello/{name}", dict)
        new_keyfs.subscribe_on_import(pkey, lambda *args: 0/0)
        serial = new_keyfs.get_current_serial()
        changes = keyfs._fs.get_changes(0)
        with pytest.raises(ZeroDivisionError):
            new_keyfs.import_changes(0, changes)
        assert new_keyfs.get_current_serial() == serial

    def test_get_raw_changelog_entry_not_exist(self, keyfs):
        assert keyfs._fs.get_raw_changelog_entry(10000) is None

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
        with keyfs.transaction(write=True):
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
        with keyfs.transaction(write=True):
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
            monkeypatch.setattr(key1.keyfs._fs, "_notify_on_commit",
                                lambda x: 0/0)
            # we prevent the hooks from getting called
            with pytest.raises(ZeroDivisionError):
                with key1.keyfs.transaction(write=True):
                    key1.set(1)
            assert key1.keyfs.get_next_serial() == 1
            assert key1.keyfs.notifier.read_event_serial() == -1
            monkeypatch.undo()

        # and then we restart keyfs and see if the hook still gets called
        with make_keyfs() as key1:
            event = queue.get()
        assert event.at_serial == 0
        assert event.typedkey == key1
        key1.keyfs.notifier.wait_event_serial(0)
        assert key1.keyfs.notifier.read_event_serial() == 0

    def test_subscribe_pattern_key(self, keyfs, queue, pool):
        pkey = keyfs.add_key("NAME1", "{name}", int)
        keyfs.notifier.on_key_change(pkey, queue.put)
        key = pkey(name="hello")
        pool.start()
        with keyfs.transaction(write=True):
            key.set(1)
        ev = queue.get()
        assert ev.typedkey == key
        assert ev.typedkey.params == {"name": "hello"}
        assert ev.typedkey.name == pkey.name

    @pytest.mark.parametrize("meth", ["wait_event_serial", "wait_tx_serial"])
    def test_wait_event_serial(self, keyfs, pool, queue, meth):
        pkey = keyfs.add_key("NAME1", "{name}", int)
        key = pkey(name="hello")
        class T:
            def __init__(self, num):
                self.num = num
            def thread_run(self):
                getattr(keyfs.notifier, meth)(self.num)
                queue.put(self.num)

        for i in range(10):
            pool.register(T(i))
        pool.start()
        for i in range(10):
            with keyfs.transaction(write=True):
                key.set(1)

        l = [queue.get() for i in range(10)]
        assert sorted(l) == list(range(10))

    def test_commit_serial(self, keyfs):
        with keyfs.transaction() as tx:
            pass
        assert tx.commit_serial is None

        with keyfs.transaction(write=True) as tx:
            assert tx.commit_serial is None
        assert tx.commit_serial is None

        key = keyfs.add_key("hello", "hello", dict)
        with keyfs.transaction(write=True) as tx:
            assert tx.at_serial == -1
            tx.set(key, {})
        assert tx.commit_serial == 0

    def test_commit_serial_restart(self, keyfs):
        key = keyfs.add_key("hello", "hello", dict)
        with keyfs.transaction() as tx:
            keyfs.restart_as_write_transaction()
            tx.set(key, {})
        assert tx.commit_serial == 0
        assert tx.write

    def test_at_serial_restart(self, keyfs):
        key = keyfs.add_key("hello", "hello", dict)
        with keyfs.transaction() as txr:
            tx = Transaction(keyfs, write=True)
            tx.set(key, {1:1})
            tx.commit()
            keyfs.restart_read_transaction()
        assert txr.commit_serial is None
        assert txr.at_serial == 0

    def test_at_serial(self, keyfs):
        with keyfs.transaction(at_serial=-1) as tx:
            assert tx.at_serial == -1

class TestRenameFileLogic:
    def test_new_content_nocrash(self, tmpdir):
        file1 = tmpdir.join("file1")
        file1_tmp = file1 + "-tmp"
        file1.write("hello")
        file1_tmp.write("this")
        pending_renames = [(str(file1_tmp), str(file1))]
        rel_renames = make_rel_renames(str(tmpdir), pending_renames)
        commit_renames(str(tmpdir), rel_renames)
        assert file1.check()
        assert file1.read() == "this"
        assert not file1_tmp.exists()
        check_pending_renames(str(tmpdir), rel_renames)
        assert file1.check()
        assert file1.read() == "this"
        assert not file1_tmp.exists()

    def test_new_content_crash(self, tmpdir, caplog):
        file1 = tmpdir.join("file1")
        file1_tmp = file1 + "-tmp"
        file1.write("hello")
        file1_tmp.write("this")
        pending_renames = [(str(file1_tmp), str(file1))]
        rel_renames = make_rel_renames(str(tmpdir), pending_renames)
        # we don't call perform_pending_renames, simulating a crash
        assert file1.read() == "hello"
        assert file1_tmp.exists()
        check_pending_renames(str(tmpdir), rel_renames)
        assert file1.check()
        assert file1.read() == "this"
        assert not file1_tmp.exists()
        assert len(caplog.getrecords(".*completed.*file-commit.*")) == 1

    def test_remove_nocrash(self, tmpdir):
        file1 = tmpdir.join("file1")
        file1.write("hello")
        pending_renames = [(None, str(file1))]
        rel_renames = make_rel_renames(str(tmpdir), pending_renames)
        commit_renames(str(tmpdir), rel_renames)
        assert not file1.exists()
        check_pending_renames(str(tmpdir), rel_renames)
        assert not file1.exists()

    def test_remove_crash(self, tmpdir, caplog):
        file1 = tmpdir.join("file1")
        file1.write("hello")
        pending_renames = [(None, str(file1))]
        rel_renames = make_rel_renames(str(tmpdir), pending_renames)
        # we don't call perform_pending_renames, simulating a crash
        assert file1.exists()
        check_pending_renames(str(tmpdir), rel_renames)
        assert not file1.exists()
        assert len(caplog.getrecords(".*completed.*file-del.*")) == 1


def test_devpiserver_22_event_serial():
    import devpi_server
    if devpi_server.__version__ == "2.2.":
        pytest.fail("change event_serial disk representation wrt -1/+1 hack")

