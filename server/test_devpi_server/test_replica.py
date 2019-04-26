# -*- coding: utf-8 -*-
import hashlib
import json
import os
import pytest
import py
from devpi_server.log import thread_pop_log
from devpi_server.fileutil import load
from devpi_server.log import threadlog, thread_push_log
from devpi_server.replica import H_EXPECTED_MASTER_ID, H_MASTER_UUID
from devpi_server.replica import H_REPLICA_UUID, H_REPLICA_OUTSIDE_URL
from devpi_server.replica import FileReplicationError
from devpi_server.replica import ImportFileReplica
from devpi_server.replica import MasterChangelogRequest
from devpi_server.replica import ReplicaThread
from devpi_server.replica import tween_replica_proxy
from pyramid.httpexceptions import HTTPNotFound
from pyramid.response import Response


def loads(bytestring):
    return load(py.io.BytesIO(bytestring))

pytestmark = [pytest.mark.notransaction]


@pytest.fixture
def replica_pypistage(devpiserver_makepypistage, replica_xom):
    return devpiserver_makepypistage(replica_xom)


@pytest.fixture
def testapp(testapp):
    testapp.xom.config.nodeinfo["role"] = "master"
    assert testapp.xom.config.role == "master"
    master_uuid = testapp.xom.config.get_master_uuid()
    assert master_uuid
    testapp.set_header_default(H_EXPECTED_MASTER_ID, master_uuid)
    return testapp


class TestChangelog:
    replica_uuid = "111"
    replica_url = "http://qwe"

    @pytest.fixture(params=[False, True])
    def reqchangelog(self, request, testapp):
        def reqchangelog(serial):
            req_headers = {H_REPLICA_UUID: self.replica_uuid,
                           H_REPLICA_OUTSIDE_URL: self.replica_url}
            url = "/+changelog/%s" % serial
            use_multi_endpoint = request.param
            if use_multi_endpoint:
                url = url + "-"
            return testapp.get(url, expect_errors=False, headers=req_headers)
        return reqchangelog

    def get_latest_serial(self, testapp):
        r = testapp.get("/+api", expect_errors=False)
        return int(r.headers["X-DEVPI-SERIAL"])

    def test_get_latest_serial(self, testapp, mapp):
        latest_serial = self.get_latest_serial(testapp)
        assert latest_serial >= -1
        mapp.create_user("hello", "pass")
        assert self.get_latest_serial(testapp) == latest_serial + 1

    def test_get_since(self, testapp, mapp, noiter, reqchangelog):
        mapp.create_user("this", password="p")
        latest_serial = self.get_latest_serial(testapp)
        r = reqchangelog(latest_serial)
        body = b''.join(r.app_iter)
        data = loads(body)
        assert "this" in str(data)

    def test_wait_entry_fails(self, testapp, mapp, noiter, monkeypatch,
                                    reqchangelog):
        mapp.create_user("this", password="p")
        latest_serial = self.get_latest_serial(testapp)
        monkeypatch.setattr(MasterChangelogRequest, "MAX_REPLICA_BLOCK_TIME", 0.01)
        r = reqchangelog(latest_serial+1)
        assert r.status_code == 202
        assert int(r.headers["X-DEVPI-SERIAL"]) == latest_serial

    def test_wait_serial_succeeds(self, blank_request, xom, mapp):
        mapp.create_user("this", password="p")
        req = blank_request()
        req.registry = {"xom": xom}
        mcr = MasterChangelogRequest(req)
        with xom.keyfs.transaction():
            with pytest.raises(HTTPNotFound):
                mcr._wait_for_serial(xom.keyfs.get_current_serial() + 10)
            serial = mcr._wait_for_serial(xom.keyfs.get_current_serial())
        assert serial == 1

    def test_master_id_mismatch(self, testapp):
        testapp.xget(400, "/+changelog/0", headers={H_EXPECTED_MASTER_ID:str("123")})
        r = testapp.xget(200, "/+changelog/0", headers={H_EXPECTED_MASTER_ID: ''})
        assert r.headers[H_MASTER_UUID]
        del testapp.headers[H_EXPECTED_MASTER_ID]
        testapp.xget(400, "/+changelog/0")


class TestMultiChangelog:
    replica_uuid = "111"
    replica_url = "http://qwe"

    @pytest.fixture
    def reqchangelogs(self, request, testapp):
        def reqchangelogs(serial):
            req_headers = {H_REPLICA_UUID: self.replica_uuid,
                           H_REPLICA_OUTSIDE_URL: self.replica_url}
            url = "/+changelog/%s-" % serial
            return testapp.get(url, expect_errors=False, headers=req_headers)
        return reqchangelogs

    def get_latest_serial(self, testapp):
        r = testapp.get("/+api", expect_errors=False)
        return int(r.headers["X-DEVPI-SERIAL"])

    def test_multiple_changes(self, mapp, noiter, reqchangelogs, testapp):
        mapp.create_user("this", password="p")
        mapp.create_user("that", password="p")
        latest_serial = self.get_latest_serial(testapp)
        assert latest_serial > 1
        r = reqchangelogs(0)
        body = b''.join(r.app_iter)
        data = loads(body)
        assert isinstance(data, list)
        assert len(data) == (latest_serial + 1)
        assert "this/.config" in str(data[-2])
        assert "that/.config" in str(data[-1])

    def test_size_limit(self, mapp, monkeypatch, noiter, reqchangelogs, testapp):
        monkeypatch.setattr(MasterChangelogRequest, "MAX_REPLICA_CHANGES_SIZE", 1024)
        mapp.create_and_login_user("this", password="p")
        for i in range(10):
            mapp.create_index("this/dev%s" % i)
        latest_serial = self.get_latest_serial(testapp)
        assert latest_serial > 1
        r = reqchangelogs(0)
        body = b''.join(r.app_iter)
        data = loads(body)
        assert isinstance(data, list)
        assert len(data) < latest_serial


def get_raw_changelog_entry(xom, serial):
    with xom.keyfs._storage.get_connection() as conn:
        return conn.get_raw_changelog_entry(serial)

class TestReplicaThread:
    @pytest.fixture
    def rt(self, makexom):
        xom = makexom(["--master=http://localhost"])
        rt = ReplicaThread(xom)
        xom.thread_pool.register(rt)
        return rt

    @pytest.fixture
    def mockchangelog(self, reqmock):
        def mockchangelog(num, code, data=b'',
                          uuid="123", headers=None):
            if headers is None:
                headers = {}
            headers = dict((k.lower(), v) for k, v in headers.items())
            if uuid is not None:
                headers.setdefault(H_MASTER_UUID.lower(), "123")
            headers.setdefault("x-devpi-serial", str(2))
            if headers["x-devpi-serial"] is None:
                del headers["x-devpi-serial"]
            reqmock.mockresponse("http://localhost/+changelog/%s" % num,
                                 code=code, data=data, headers=headers)
        return mockchangelog

    def test_thread_run_fail(self, rt, mockchangelog, caplog):
        rt.thread.sleep = lambda x: 0/0
        mockchangelog(0, code=404)
        with pytest.raises(ZeroDivisionError):
            rt.thread_run()
        assert caplog.getrecords("404.*failed fetching*")

    def test_thread_run_decode_error(self, rt, mockchangelog, caplog):
        rt.thread.sleep = lambda x: 0/0
        mockchangelog(0, code=200, data=b'qwelk')
        with pytest.raises(ZeroDivisionError):
            rt.thread_run()
        assert caplog.getrecords("could not process")

    def test_thread_run_recovers_from_error(self, mock, rt, reqmock, mockchangelog, caplog, xom):
        import socket
        # setup a regular request
        data = get_raw_changelog_entry(xom, 0)
        mockchangelog(0, code=200, data=data)
        # get the result
        orig_req = reqmock.url2reply[("http://localhost/+changelog/0", None)]
        # setup so the first attempt fails, then the second succeeds
        reqmock.url2reply = mock.Mock()
        reqmock.url2reply.get.side_effect = [socket.error(), orig_req]
        rt.thread.sleep = mock.Mock()
        rt.thread.sleep.side_effect = [
            # 1. sleep
            0,
            # 2. raise exception to get into exception part of while loop
            ZeroDivisionError(),
            # 3. kill the thread
            ZeroDivisionError()]
        # run
        with pytest.raises(ZeroDivisionError):
            rt.thread_run()
        msgs = [x.msg for x in caplog.getrecords(r".*http://localhost/\+changelog/0")]
        assert msgs == [
            '[REP] fetching %s',
            '[REP] error fetching %s: %s',
            '[REP] fetching %s']

    def test_thread_run_ok(self, rt, mockchangelog, caplog, xom):
        rt.thread.sleep = lambda *x: 0/0
        data = get_raw_changelog_entry(xom, 0)
        mockchangelog(0, code=200, data=data)
        mockchangelog(1, code=404, data=data)
        with pytest.raises(ZeroDivisionError):
            rt.thread_run()
        assert caplog.getrecords("committed")

    def test_thread_run_no_uuid(self, rt, mockchangelog, caplog, xom):
        rt.thread.sleep = lambda x: 0/0
        mockchangelog(0, code=200, data=b'123', uuid=None)
        with pytest.raises(ZeroDivisionError):
            rt.thread_run()
        assert caplog.getrecords("remote.*no.*UUID")

    def test_thread_run_ok_uuid_change(self, rt, mockchangelog, caplog, xom, monkeypatch):
        monkeypatch.setattr("os._exit", lambda n: 0/0)
        rt.thread.sleep = lambda *x: 0/0
        data = get_raw_changelog_entry(xom, 0)
        mockchangelog(0, code=200, data=data)
        mockchangelog(1, code=200, data=data,
                      headers={"x-devpi-master-uuid": "001"})
        with pytest.raises(ZeroDivisionError):
            rt.thread_run()
        assert caplog.getrecords("master UUID.*001.*does not match")

    def test_thread_run_serial_mismatch(self, rt, mockchangelog, caplog, xom, monkeypatch):
        monkeypatch.setattr("os._exit", lambda n: 0/0)
        rt.thread.sleep = lambda *x: 0/0

        # we need to have at least two commits
        with xom.keyfs.transaction(write=True):
            xom.model.create_user("qlwkej", "qwe")

        data = get_raw_changelog_entry(xom, 0)
        mockchangelog(0, code=200, data=data)
        data = get_raw_changelog_entry(xom, 1)
        mockchangelog(1, code=200, data=data,
                      headers={"x-devpi-serial": "0"})
        with pytest.raises(ZeroDivisionError):
            rt.thread_run()
        assert caplog.getrecords("Got serial 0 from master which is smaller than last "
                    "recorded serial")

    def test_thread_run_invalid_serial(self, rt, mockchangelog, caplog, xom, monkeypatch):
        monkeypatch.setattr("os._exit", lambda n: 0/0)
        rt.thread.sleep = lambda *x: 0/0
        data = get_raw_changelog_entry(xom, 0)
        assert data
        mockchangelog(0, code=200, data=data)
        data = get_raw_changelog_entry(xom, 1)
        mockchangelog(1, code=200, data=data,
                      headers={"x-devpi-serial": "foo"})
        with pytest.raises(ZeroDivisionError):
            rt.thread_run()
        assert caplog.getrecords("error fetching.*invalid literal for int")

    def test_thread_run_missing_serial(self, rt, mockchangelog, caplog, xom, monkeypatch):
        monkeypatch.setattr("os._exit", lambda n: 0/0)
        rt.thread.sleep = lambda *x: 0/0
        data = get_raw_changelog_entry(xom, 0)
        mockchangelog(0, code=200, data=data)
        data = get_raw_changelog_entry(xom, 1)
        mockchangelog(1, code=200, data=data,
                      headers={"x-devpi-serial": None})
        with pytest.raises(ZeroDivisionError):
            rt.thread_run()
        assert caplog.getrecords("error fetching.*x-devpi-serial")

    def test_thread_run_try_again(self, rt, mockchangelog, caplog):
        l = [1]
        def exit_if_shutdown():
            l.pop()
        rt.thread.exit_if_shutdown = exit_if_shutdown
        mockchangelog(0, code=202)
        with pytest.raises(IndexError):
            rt.thread_run()
        assert caplog.getrecords("trying again")


def test_clean_request_headers(blank_request):
    from devpi_server.replica import clean_request_headers
    request = blank_request()
    request.headers['Foo'] = 'bar'
    assert 'host' in request.headers
    assert 'foo' in request.headers
    headers = clean_request_headers(request)
    assert 'host' not in headers
    assert 'foo' in headers


def test_clean_response_headers(mock):
    from devpi_server.replica import clean_response_headers
    response = mock.Mock()
    response.headers = dict(foo='bar')
    # make sure the result is a case insensitive header dict
    headers = clean_response_headers(response)
    assert 'foo' in headers
    assert 'FOO' in headers
    assert 'bar' not in headers
    headers['egg'] = 'ham'
    assert 'egg' in headers
    assert 'EGG' in headers


class TestTweenReplica:
    def test_nowrite(self, xom, blank_request):
        l = []
        def wrapped_handler(request):
            l.append(xom.keyfs.get_current_serial())
            return Response("")
        handler = tween_replica_proxy(wrapped_handler, {"xom": xom})
        handler(blank_request())
        assert l == [xom.keyfs.get_current_serial()]

    def test_write_proxies(self, makexom, blank_request, reqmock, monkeypatch):
        xom = makexom(["--master", "http://localhost"])
        reqmock.mock("http://localhost/blankpath",
                     code=200, headers={"X-DEVPI-SERIAL": "10"})
        l = []
        monkeypatch.setattr(xom.keyfs, "wait_tx_serial",
                            lambda x: l.append(x))
        handler = tween_replica_proxy(None, {"xom": xom})
        response = handler(blank_request(method="PUT"))
        assert response.headers.get("X-DEVPI-SERIAL") == "10"
        assert l == [10]

    def test_preserve_reason(self, makexom, blank_request, reqmock, monkeypatch):
        xom = makexom(["--master", "http://localhost"])
        reqmock.mock("http://localhost/blankpath",
                     code=200, reason="GOOD", headers={"X-DEVPI-SERIAL": "10"})
        l = []
        monkeypatch.setattr(xom.keyfs, "wait_tx_serial",
                            lambda x: l.append(x))
        handler = tween_replica_proxy(None, {"xom": xom})
        response = handler(blank_request(method="PUT"))
        assert response.status == "200 GOOD"

    def test_write_proxies_redirect(self, makexom, blank_request, reqmock, monkeypatch):
        xom = makexom(["--master", "http://localhost",
                       "--outside-url=http://my.domain"])
        reqmock.mock("http://localhost/blankpath",
                     code=302, headers={"X-DEVPI-SERIAL": "10",
                                        "location": "http://localhost/hello"}
        )
        l = []
        monkeypatch.setattr(xom.keyfs, "wait_tx_serial",
                            lambda x: l.append(x))
        handler = tween_replica_proxy(None, {"xom": xom})
        # normally the app is wrapped by OutsideURLMiddleware, since this is
        # not the case here, we have to set the host explicitly
        response = handler(
            blank_request(method="PUT", headers=dict(host='my.domain')))
        assert response.headers.get("X-DEVPI-SERIAL") == "10"
        assert response.headers.get("location") == "http://my.domain/hello"
        assert l == [10]

    def test_hop_headers(self, makexom, blank_request, reqmock, monkeypatch):
        xom = makexom(["--master", "http://localhost"])
        reqmock.mock("http://localhost/blankpath",
                     code=200, headers={
                        "Connection": "Keep-Alive, Foo",
                        "Foo": "abc",
                        "Keep-Alive": "timeout=30",
                        "X-DEVPI-SERIAL": "0"})
        monkeypatch.setattr(xom.keyfs, "wait_tx_serial",
                            lambda x: x)
        handler = tween_replica_proxy(None, {"xom": xom})
        response = handler(blank_request(method="PUT"))
        assert 'connection' not in response.headers
        assert 'foo' not in response.headers
        assert 'keep-alive' not in response.headers

def replay(xom, replica_xom, events=True):
    threadlog.info("test: replaying replica")
    for serial in range(replica_xom.keyfs.get_next_serial(),
                        xom.keyfs.get_next_serial()):
        if serial == -1:
            continue
        with xom.keyfs._storage.get_connection() as conn:
            change_entry = conn.get_changes(serial)
        threadlog.info("test: importing to replica %s", serial)
        replica_xom.keyfs.import_changes(serial, change_entry)

    # replay notifications
    if events:
        noti_thread = replica_xom.keyfs.notifier
        event_serial = noti_thread.read_event_serial()
        thread_push_log("NOTI")
        while event_serial < replica_xom.keyfs.get_current_serial():
            event_serial += 1
            noti_thread._execute_hooks(event_serial, threadlog, raising=True)
            noti_thread.write_event_serial(event_serial)
        thread_pop_log("NOTI")


@pytest.fixture
def make_replica_xom(makexom):
    def make_replica_xom(options=()):
        from devpi_server.replica import ReplicationErrors
        replica_xom = makexom(["--master", "http://localhost"] + list(options))
        keyfs = replica_xom.keyfs
        replica_xom.errors = ReplicationErrors(replica_xom.config.serverdir)
        for key in (keyfs.STAGEFILE, keyfs.PYPIFILE_NOMD5):
            keyfs.subscribe_on_import(
                key, ImportFileReplica(replica_xom, replica_xom.errors))
        return replica_xom
    return make_replica_xom


class TestUseExistingFiles:
    def test_use_existing_files(self, caplog, make_replica_xom, mapp, monkeypatch, tmpdir, xom):
        # this will be the folder to find existing files in the replica
        existing_base = tmpdir.join('existing').ensure_dir()
        # prepare data on master
        mapp.create_and_use()
        content1 = mapp.makepkg("hello-1.0.zip", b"content1", "hello", "1.0")
        mapp.upload_file_pypi("hello-1.0.zip", content1, "hello", "1.0")
        # get the path of the release
        (path,) = mapp.get_release_paths('hello')
        # create the file
        existing_path = existing_base.join(path)
        existing_path.dirpath().ensure_dir()
        existing_path.write_binary(content1)
        # create the replica with the path to existing files
        replica_xom = make_replica_xom(options=[
            '--replica-file-search-path', existing_base.strpath])
        # now sync the replica, if the file is not found there will be an error
        # because httpget is mocked
        replay(xom, replica_xom)
        assert len(caplog.getrecords('checking existing file')) == 1

    @pytest.mark.storage_with_filesystem
    @pytest.mark.skipif(not hasattr(os, 'link'),
                        reason="OS doesn't support hard links")
    def test_hardlink(self, caplog, make_replica_xom, mapp, monkeypatch, tmpdir, xom):
        # this will be the folder to find existing files in the replica
        existing_base = tmpdir.join('existing').ensure_dir()
        # prepare data on master
        mapp.create_and_use()
        content1 = mapp.makepkg("hello-1.0.zip", b"content1", "hello", "1.0")
        mapp.upload_file_pypi("hello-1.0.zip", content1, "hello", "1.0")
        # get the path of the release
        (path,) = mapp.get_release_paths('hello')
        # create the file
        existing_path = existing_base.join(path)
        existing_path.dirpath().ensure_dir()
        existing_path.write_binary(content1)
        assert existing_path.stat().nlink == 1
        # create the replica with the path to existing files and using hard links
        replica_xom = make_replica_xom(options=[
            '--replica-file-search-path', existing_base.strpath,
            '--hard-links'])
        # now sync the replica, if the file is not found there will be an error
        # because httpget is mocked
        replay(xom, replica_xom)
        assert len(caplog.getrecords('checking existing file')) == 1
        # check the number of links of the file
        assert existing_path.stat().nlink == 2


class TestFileReplication:
    @pytest.fixture
    def replica_xom(self, make_replica_xom):
        return make_replica_xom()

    def test_no_set_default_indexes(self, replica_xom):
        assert replica_xom.keyfs.get_current_serial() == -1

    def test_nowrite(self, replica_xom):
        with pytest.raises(replica_xom.keyfs.ReadOnly):
            with replica_xom.keyfs.transaction(write=True):
                pass
        with pytest.raises(replica_xom.keyfs.ReadOnly):
            with replica_xom.keyfs.transaction():
                replica_xom.keyfs.restart_as_write_transaction()


    def test_transaction_api(self, replica_xom, xom):
        with xom.keyfs.transaction(write=True):
            xom.model.create_user("hello", "pass")
        with xom.keyfs.transaction(write=True):
            xom.model.create_user("world", "pass")

        replay(xom, replica_xom)

        serial = xom.keyfs.get_current_serial() - 1
        with replica_xom.keyfs.transaction(at_serial=serial):
            assert not replica_xom.model.get_user("world")
            assert replica_xom.model.get_user("hello")

    def test_fetch(self, gen, reqmock, xom, replica_xom):
        replay(xom, replica_xom)
        content1 = b'hello'
        md5 = hashlib.md5(content1).hexdigest()
        link = gen.pypi_package_link("pytest-1.8.zip#md5=%s" % md5, md5=False)
        with xom.keyfs.transaction(write=True):
            entry = xom.filestore.maplink(link, "root", "pypi", "pytest")
            assert not entry.file_exists()

        replay(xom, replica_xom)
        with replica_xom.keyfs.transaction():
            r_entry = replica_xom.filestore.get_file_entry(entry.relpath)
            assert not r_entry.file_exists()
            assert r_entry.meta

        with xom.keyfs.transaction(write=True):
            entry.file_set_content(content1)

        # first we try to return something wrong
        master_url = replica_xom.config.master_url
        master_file_path = master_url.joinpath(entry.relpath).url
        xom.httpget.mockresponse(master_file_path, code=200, content=b'13')
        replay(xom, replica_xom)
        assert list(replica_xom.errors.errors.keys()) == [
            'root/pypi/+f/5d4/1402abc4b2a76/pytest-1.8.zip']
        with replica_xom.errors.errorsfn.open() as f:
            persisted_errors = json.load(f)
        assert persisted_errors == replica_xom.errors.errors
        with replica_xom.keyfs.transaction():
            assert not r_entry.file_exists()
            assert not replica_xom.filestore.storedir.join(r_entry.relpath).exists()

        # then we try to return the correct thing
        with xom.keyfs.transaction(write=True):
            entry.file_set_content(content1)
        xom.httpget.mockresponse(master_file_path, code=200, content=content1)
        replay(xom, replica_xom)
        assert replica_xom.errors.errors == {}
        with replica_xom.errors.errorsfn.open() as f:
            persisted_errors = json.load(f)
        assert persisted_errors == replica_xom.errors.errors
        with replica_xom.keyfs.transaction():
            assert r_entry.file_exists()
            assert r_entry.file_get_content() == content1

        # now we produce a delete event
        with xom.keyfs.transaction(write=True):
            entry.delete()
        replay(xom, replica_xom)
        with replica_xom.keyfs.transaction():
            assert not r_entry.file_exists()

    def test_fetch_later_deleted(self, gen, reqmock, xom, replica_xom):
        replay(xom, replica_xom)
        content1 = b'hello'
        md5 = hashlib.md5(content1).hexdigest()
        link = gen.pypi_package_link("pytest-1.8.zip#md5=%s" % md5, md5=False)
        with xom.keyfs.transaction(write=True):
            entry = xom.filestore.maplink(link, "root", "pypi", "pytest")
            assert not entry.file_exists()

        master_url = replica_xom.config.master_url
        master_file_path = master_url.joinpath(entry.relpath).url

        # first we create
        with xom.keyfs.transaction(write=True):
            entry.file_set_content(content1)

        # then we delete
        with xom.keyfs.transaction(write=True):
            entry.file_delete()
            entry.delete()
        assert not xom.filestore.storedir.join(entry.relpath).exists()

        # and simulate what the master will respond
        xom.httpget.mockresponse(master_file_path, status_code=410)

        # and then we try to see if we can replicate the create and del changes
        replay(xom, replica_xom)

        with replica_xom.keyfs.transaction():
            r_entry = replica_xom.filestore.get_file_entry(entry.relpath)
            assert not r_entry.file_exists()

    def test_fetch_pypi_nomd5(self, gen, reqmock, xom, replica_xom):
        replay(xom, replica_xom)
        content1 = b'hello'
        link = gen.pypi_package_link("some-1.8.zip", md5=False)
        with xom.keyfs.transaction(write=True):
            entry = xom.filestore.maplink(link, "root", "pypi", "some")
            assert not entry.file_exists()
            assert not entry.hash_spec

        replay(xom, replica_xom)
        with replica_xom.keyfs.transaction():
            r_entry = replica_xom.filestore.get_file_entry(entry.relpath)
            assert not r_entry.file_exists()
            assert r_entry.meta
            assert not r_entry.hash_spec

        with xom.keyfs.transaction(write=True):
            entry.file_set_content(content1)

        master_url = replica_xom.config.master_url
        master_file_path = master_url.joinpath(entry.relpath).url
        # simulate some 500 master server error
        replica_xom.httpget.mockresponse(master_file_path, status_code=500,
                                         content=b'')
        with pytest.raises(FileReplicationError) as e:
            replay(xom, replica_xom)
        assert str(e.value) == 'FileReplicationError with http://localhost/root/pypi/+e/https_pypi.org_package_some/some-1.8.zip, code=500, reason=Internal Server Error, relpath=root/pypi/+e/https_pypi.org_package_some/some-1.8.zip, message=failed'

        # now get the real thing
        replica_xom.httpget.mockresponse(master_file_path, status_code=200,
                                         content=content1)
        replay(xom, replica_xom)
        with replica_xom.keyfs.transaction():
            assert r_entry.file_exists()
            assert r_entry.file_get_content() == content1

    def test_cache_remote_file_fails(self, xom, replica_xom, gen,
                                     pypistage, monkeypatch, reqmock):
        l = []
        monkeypatch.setattr(xom.keyfs, "wait_tx_serial",
                            lambda x: l.append(x))
        with xom.keyfs.transaction(write=True):
            link = gen.pypi_package_link("pytest-1.8.zip", md5=True)
            entry = xom.filestore.maplink(link, "root", "pypi", "pytest")
            assert entry.hash_spec and not entry.file_exists()
        replay(xom, replica_xom)
        with replica_xom.keyfs.transaction():
            entry = replica_xom.filestore.get_file_entry(entry.relpath)
            url = replica_xom.config.master_url.joinpath(entry.relpath).url
            pypistage.httpget.mockresponse(url, status_code=500)
            with pytest.raises(entry.BadGateway) as e:
                for part in entry.iter_remote_file_replica():
                    pass
            e.match('received 500 from master')
            e.match('pypi.org/package/some/pytest-1.8.zip: received 404')

    def test_cache_remote_file_fetch_original(self, xom, replica_xom, gen,
                                              pypistage, monkeypatch, reqmock):
        l = []
        monkeypatch.setattr(xom.keyfs, "wait_tx_serial",
                            lambda x: l.append(x))
        with xom.keyfs.transaction(write=True):
            md5 = hashlib.md5()
            md5.update(b'123')
            link = gen.pypi_package_link(
                "pytest-1.8.zip", md5=md5.hexdigest())
            entry = xom.filestore.maplink(link, "root", "pypi", "pytest")
            assert entry.hash_spec and not entry.file_exists()
        replay(xom, replica_xom)
        with replica_xom.keyfs.transaction():
            headers = {
                "content-length": "3",
                "last-modified": "Thu, 25 Nov 2010 20:00:27 GMT",
                "content-type": ("application/zip", None)}
            entry = replica_xom.filestore.get_file_entry(entry.relpath)
            url = replica_xom.config.master_url.joinpath(entry.relpath).url
            pypistage.httpget.mockresponse(url, status_code=500)
            pypistage.httpget.mockresponse(
                entry.url, headers=headers, content=b'123')
            result = entry.iter_remote_file_replica()
            headers = next(result)
            assert headers['content-length'] == '3'
            assert b''.join(result) == b'123'

    def test_checksum_mismatch(self, xom, replica_xom, gen, maketestapp,
                               makemapp, reqmock):
        # this test might seem to be doing the same as test_fetch above, but
        # test_fetch creates a new transaction for the same file, which doesn't
        # happen 'in real life'™
        from devpi_server.replica import ReplicationErrors
        app = maketestapp(xom)
        mapp = makemapp(app)
        api = mapp.create_and_use()
        content1 = mapp.makepkg("hello-1.0.zip", b"content1", "hello", "1.0")
        mapp.upload_file_pypi("hello-1.0.zip", content1, "hello", "1.0")
        r_app = maketestapp(replica_xom)
        # first we try to return something wrong
        master_url = replica_xom.config.master_url
        (path,) = mapp.get_release_paths('hello')
        file_relpath = '+files' + path
        master_file_url = master_url.joinpath(path).url
        replica_xom.httpget.mockresponse(master_file_url, code=200, content=b'13')
        replay(xom, replica_xom)
        assert xom.keyfs.get_current_serial() == replica_xom.keyfs.get_current_serial()
        replication_errors = ReplicationErrors(replica_xom.config.serverdir)
        assert list(replication_errors.errors.keys()) == [
            '%s/+f/d0b/425e00e15a0d3/hello-1.0.zip' % api.stagename]
        # the master and replica are in sync, so getting the file on the
        # replica needs to fetch it again
        headers = {"content-length": "8",
                   "last-modified": "Thu, 25 Nov 2010 20:00:27 GMT",
                   "content-type": "application/zip",
                   "X-DEVPI-SERIAL": str(xom.keyfs.get_current_serial())}
        reqmock.mockresponse(master_file_url, code=200, headers=headers)
        replica_xom.httpget.mockresponse(master_file_url, code=200, content=content1, headers=headers)
        with replica_xom.keyfs.transaction(write=False) as tx:
            assert not tx.conn.io_file_exists(file_relpath)
        r = r_app.get(path)
        assert r.status_code == 200
        assert r.body == content1
        with replica_xom.keyfs.transaction(write=False) as tx:
            assert tx.conn.io_file_exists(file_relpath)
        replication_errors = ReplicationErrors(replica_xom.config.serverdir)
        assert list(replication_errors.errors.keys()) == []


def test_should_fetch_remote_file():
    from devpi_server.views import should_fetch_remote_file
    from devpi_server.replica import H_REPLICA_FILEREPL
    class Entry:
        eggfragment = "some"
        def file_exists(self):
            return True
    assert should_fetch_remote_file(Entry(), {})
    assert not \
           should_fetch_remote_file(Entry(), {H_REPLICA_FILEREPL: str("YES")})


def test_simplelinks_update_updates_projectname(httpget, monkeypatch,
    pypistage, replica_pypistage, pypiurls, replica_xom, xom):

    pypistage.mock_simple_projects([])
    pypistage.mock_simple("pytest", pkgver="pytest-1.0.zip")
    with xom.keyfs.transaction():
        assert not pypistage.list_projects_perstage()

    with xom.keyfs.transaction():
        pypistage.get_simplelinks("pytest")

    # replicate including executing events
    replay(xom, replica_xom)

    with replica_xom.keyfs.transaction():
        st = replica_xom.model.getstage(pypistage.name)
        assert st.list_projects_perstage() == set(["pytest"])


def test_get_simplelinks_perstage(httpget, monkeypatch, pypistage, replica_pypistage,
                                  pypiurls, replica_xom, xom):
    orig_simple = pypiurls.simple

    # prepare the data on master
    pypistage.mock_simple("pytest", pkgver="pytest-1.0.zip")
    with xom.keyfs.transaction(write=True):
        pypistage.get_releaselinks("pytest")

    # replicate the state
    replay(xom, replica_xom)

    # now check
    pypiurls.simple = 'http://localhost:3111/root/pypi/+simple/'
    serial = xom.keyfs.get_current_serial()
    httpget.mock_simple(
        'pytest',
        text='<a href="https://pypi.org/pytest/pytest-1.0.zip">pytest-1.0.zip</a>',
        headers={'X-DEVPI-SERIAL': str(serial)})
    with replica_xom.keyfs.transaction():
        ret = replica_pypistage.get_releaselinks("pytest")
    assert len(ret) == 1
    assert ret[0].relpath == 'root/pypi/+e/https_pypi.org_pytest/pytest-1.0.zip'

    # now we change the links and expire the cache
    pypiurls.simple = orig_simple
    pypistage.mock_simple("pytest", pkgver="pytest-1.1.zip", pypiserial=10001)
    pypistage.cache_retrieve_times.expire('pytest')
    with xom.keyfs.transaction(write=True):
        pypistage.get_releaselinks("pytest")
    assert xom.keyfs.get_current_serial() > serial

    # we patch wait_tx_serial so we can check and replay
    called = []
    def wait_tx_serial(serial, timeout=None):
        called.append(True)
        assert xom.keyfs.get_current_serial() == serial
        assert replica_xom.keyfs.get_current_serial() < serial
        replay(xom, replica_xom, events=False)
        assert replica_xom.keyfs.get_current_serial() == serial
        return True

    monkeypatch.setattr(replica_xom.keyfs, 'wait_tx_serial', wait_tx_serial)
    pypiurls.simple = 'http://localhost:3111/root/pypi/+simple/'
    httpget.mock_simple(
        'pytest',
        text='<a href="https://pypi.org/pkg/pytest-1.1.zip">pytest-1.1.zip</a>',
        pypiserial=10001,
        headers={'X-DEVPI-SERIAL': str(xom.keyfs.get_current_serial())})
    with replica_xom.keyfs.transaction():
        # make the replica believe it hasn't updated for a longer time
        r_pypistage = replica_xom.model.getstage("root/pypi")
        r_pypistage.cache_retrieve_times.expire("pytest")
        ret = replica_pypistage.get_releaselinks("pytest")
    assert called == [True]
    replay(xom, replica_xom)
    assert len(ret) == 1
    assert ret[0].relpath == 'root/pypi/+e/https_pypi.org_pytest/pytest-1.1.zip'


def test_replicate_deleted_user(mapp, replica_xom):
    mapp.create_and_use("hello/dev")
    content = mapp.makepkg("hello-1.0.tar.gz", b"content", "hello", "1.0")
    mapp.upload_file_pypi("hello-1.0.tar.gz", content, "hello", "1.0")
    mapp.delete_user("hello")

    # replicate the state
    replay(mapp.xom, replica_xom)


def test_auth_status_master_down(maketestapp, replica_xom, mock):
    from devpi_server.model import UpstreamError
    testapp = maketestapp(replica_xom)
    calls = []
    with mock.patch('devpi_server.replica.proxy_request_to_master') as prtm:
        def proxy_request_to_master(*args, **kwargs):
            calls.append((args, kwargs))
            raise UpstreamError("foo")
        prtm.side_effect = proxy_request_to_master
        r = testapp.get('/+api')
    assert len(calls) == 1
    assert calls[0][0][1].url == 'http://localhost/+api'
    assert r.json['result']['authstatus'] == ['fail', '', []]
