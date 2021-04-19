# -*- coding: utf-8 -*-
import hashlib
import os
import pytest
from devpi_server.log import thread_pop_log
from devpi_server.fileutil import loads
from devpi_server.keyfs import MissingFileException
from devpi_server.log import threadlog, thread_push_log
from devpi_server.replica import H_EXPECTED_MASTER_ID, H_MASTER_UUID
from devpi_server.replica import H_REPLICA_UUID, H_REPLICA_OUTSIDE_URL
from devpi_server.replica import MasterChangelogRequest
from devpi_server.replica import proxy_view_to_master
from devpi_server.views import iter_remote_file_replica
from pyramid.httpexceptions import HTTPNotFound


pytestmark = [pytest.mark.notransaction]


@pytest.fixture
def auth_serializer(xom):
    import itsdangerous

    return itsdangerous.TimedSerializer(
        xom.config.get_replica_secret())


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
    def reqchangelog(self, request, auth_serializer, testapp, xom):
        def reqchangelog(serial):
            token = auth_serializer.dumps(self.replica_uuid)
            req_headers = {H_REPLICA_UUID: self.replica_uuid,
                           H_REPLICA_OUTSIDE_URL: self.replica_url,
                           str('Authorization'): 'Bearer %s' % token}
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

    def test_master_id_mismatch(self, auth_serializer, testapp):
        token = auth_serializer.dumps(self.replica_uuid)
        testapp.xget(400, "/+changelog/0", headers={
            H_REPLICA_UUID: self.replica_uuid,
            H_EXPECTED_MASTER_ID:str("123"),
            str('Authorization'): 'Bearer %s' % token})
        r = testapp.xget(200, "/+changelog/0", headers={
            H_REPLICA_UUID: self.replica_uuid,
            H_EXPECTED_MASTER_ID: '',
            str('Authorization'): 'Bearer %s' % token})
        assert r.headers[H_MASTER_UUID]
        del testapp.headers[H_EXPECTED_MASTER_ID]
        testapp.xget(400, "/+changelog/0")


class TestMultiChangelog:
    replica_uuid = "111"
    replica_url = "http://qwe"

    @pytest.fixture
    def reqchangelogs(self, request, auth_serializer, testapp):
        def reqchangelogs(serial):
            token = auth_serializer.dumps(self.replica_uuid)
            req_headers = {H_REPLICA_UUID: self.replica_uuid,
                           H_REPLICA_OUTSIDE_URL: self.replica_url,
                           str('Authorization'): 'Bearer %s' % token}
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
        return xom.replica_thread

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
            url = "http://localhost/+changelog/%s" % num
            if num == 0:
                url = url + '?initial_fetch'
            reqmock.mockresponse(url, code=code, data=data, headers=headers)
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
        orig_req = reqmock.url2reply[("http://localhost/+changelog/0?initial_fetch", None)]
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


class TestProxyViewToMaster:
    def test_write_proxies(self, makexom, blank_request, reqmock, monkeypatch):
        xom = makexom(["--master", "http://localhost"])
        reqmock.mock("http://localhost/blankpath",
                     code=200, headers={"X-DEVPI-SERIAL": "10"})
        l = []
        monkeypatch.setattr(xom.keyfs, "wait_tx_serial",
                            lambda x: l.append(x))
        request = blank_request(method="PUT")
        request.registry = dict(xom=xom)
        response = proxy_view_to_master(None, request)
        assert response.headers.get("X-DEVPI-SERIAL") == "10"
        assert l == [10]

    def test_preserve_reason(self, makexom, blank_request, reqmock, monkeypatch):
        xom = makexom(["--master", "http://localhost"])
        reqmock.mock("http://localhost/blankpath",
                     code=200, reason="GOOD", headers={"X-DEVPI-SERIAL": "10"})
        l = []
        monkeypatch.setattr(xom.keyfs, "wait_tx_serial",
                            lambda x: l.append(x))
        request = blank_request(method="PUT")
        request.registry = dict(xom=xom)
        response = proxy_view_to_master(None, request)
        assert response.status == "200 GOOD"

    def test_write_proxies_redirect(self, makexom, blank_request, reqmock, monkeypatch):
        xom = makexom(["--master", "http://localhost",
                       "--outside-url=http://my.domain"])
        reqmock.mock("http://localhost/blankpath",
                     code=302, headers={"X-DEVPI-SERIAL": "10",
                                        "location": "http://localhost/hello"})
        l = []
        monkeypatch.setattr(xom.keyfs, "wait_tx_serial",
                            lambda x: l.append(x))
        # normally the app is wrapped by OutsideURLMiddleware, since this is
        # not the case here, we have to set the host explicitly
        request = blank_request(method="PUT", headers=dict(host='my.domain'))
        request.registry = dict(xom=xom)
        response = proxy_view_to_master(None, request)
        assert response.headers.get("X-DEVPI-SERIAL") == "10"
        assert response.headers.get("location") == "http://my.domain/hello"
        assert l == [10]

    def test_hop_headers(self, makexom, blank_request, reqmock, monkeypatch):
        xom = makexom(["--master", "http://localhost"])
        reqmock.mock(
            "http://localhost/blankpath",
            code=200, headers={
                "Connection": "Keep-Alive, Foo",
                "Foo": "abc",
                "Keep-Alive": "timeout=30",
                "X-DEVPI-SERIAL": "0"})
        monkeypatch.setattr(xom.keyfs, "wait_tx_serial",
                            lambda x: x)
        request = blank_request(method="PUT")
        request.registry = dict(xom=xom)
        response = proxy_view_to_master(None, request)
        assert 'connection' not in response.headers
        assert 'foo' not in response.headers
        assert 'keep-alive' not in response.headers


def replay(xom, replica_xom, events=True):
    if replica_xom.replica_thread.replica_in_sync_at is None:
        # allow on_import to run right away, so we don't need to rely
        # on the initial import thread for tests
        replica_xom.replica_thread.replica_in_sync_at = 0

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
        replica_xom.replica_thread.wait()
        noti_thread = replica_xom.keyfs.notifier
        event_serial = noti_thread.read_event_serial()
        thread_push_log("NOTI")
        while event_serial < replica_xom.keyfs.get_current_serial():
            event_serial += 1
            noti_thread._execute_hooks(event_serial, threadlog, raising=True)
            noti_thread.write_event_serial(event_serial)
        thread_pop_log("NOTI")


@pytest.fixture
def make_replica_xom(makexom, secretfile):
    def make_replica_xom(options=()):
        replica_xom = makexom([
            "--master", "http://localhost",
            "--file-replication-threads", "1",
            "--secretfile", secretfile.strpath] + list(options))
        # shorten error delay for tests
        replica_xom.replica_thread.shared_data.ERROR_QUEUE_MAX_DELAY = 0.1
        replica_xom.thread_pool.start_one(replica_xom.replica_thread)
        replica_xom.thread_pool.start_one(
            replica_xom.replica_thread.file_replication_threads[0])
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
        replay(xom, replica_xom, events=False)
        replica_xom.replica_thread.wait()
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

    def test_use_existing_files_bad_data(self, caplog, make_replica_xom, mapp, monkeypatch, patch_reqsessionmock, tmpdir, xom):
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
        existing_path.write_binary(b"bad_data")
        # create the replica with the path to existing files
        replica_xom = make_replica_xom(options=[
            '--replica-file-search-path', existing_base.strpath])
        (frthread,) = replica_xom.replica_thread.file_replication_threads
        frt_reqmock = patch_reqsessionmock(frthread.session)
        frt_reqmock.mockresponse("http://localhost" + path, 200, data=content1)
        # now sync the replica, if the file is not found there will be an error
        # because httpget is mocked
        replay(xom, replica_xom, events=False)
        replica_xom.replica_thread.wait()
        assert len(caplog.getrecords('checking existing file')) == 1
        assert len(caplog.getrecords('sha256 mismatch, got ec7d057f450dc963f15978af98b9cdda64aca6751c677e45d4a358fe103dc05b')) == 1
        with replica_xom.keyfs.transaction(write=False):
            entry = replica_xom.filestore.get_file_entry(path[1:])
            assert entry.file_get_content() == content1

    @pytest.mark.storage_with_filesystem
    @pytest.mark.skipif(not hasattr(os, 'link'),
                        reason="OS doesn't support hard links")
    def test_hardlink_bad_data(self, caplog, make_replica_xom, mapp, monkeypatch, patch_reqsessionmock, tmpdir, xom):
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
        existing_path.write_binary(b"bad_data")
        assert existing_path.stat().nlink == 1
        # create the replica with the path to existing files and using hard links
        replica_xom = make_replica_xom(options=[
            '--replica-file-search-path', existing_base.strpath,
            '--hard-links'])
        (frthread,) = replica_xom.replica_thread.file_replication_threads
        frt_reqmock = patch_reqsessionmock(frthread.session)
        frt_reqmock.mockresponse("http://localhost" + path, 200, data=content1)
        # now sync the replica, if the file is not found there will be an error
        # because httpget is mocked
        replay(xom, replica_xom)
        assert len(caplog.getrecords('checking existing file')) == 1
        assert len(caplog.getrecords('sha256 mismatch, got ec7d057f450dc963f15978af98b9cdda64aca6751c677e45d4a358fe103dc05b')) == 1
        # check the number of links of the file
        assert existing_path.stat().nlink == 1
        with replica_xom.keyfs.transaction(write=False):
            entry = replica_xom.filestore.get_file_entry(path[1:])
            assert entry.file_get_content() == content1


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
            assert entry.file_exists()
            assert entry.last_modified is not None

        # first we try to return something wrong
        master_url = replica_xom.config.master_url
        master_file_path = master_url.joinpath(entry.relpath).url
        reqmock.mockresponse(master_file_path, code=200, data=b'13')
        replay(xom, replica_xom, events=False)
        replica_xom.replica_thread.wait(error_queue=True)
        replication_errors = replica_xom.replica_thread.shared_data.errors
        assert list(replication_errors.errors.keys()) == [
            'root/pypi/+f/5d4/1402abc4b2a76/pytest-1.8.zip']
        with replica_xom.keyfs.transaction():
            assert not r_entry.file_exists()
            assert not replica_xom.config.serverdir.join(r_entry._storepath).exists()

        # then we try to return the correct thing
        with xom.keyfs.transaction(write=True):
            # trigger a change
            entry.last_modified = 'Fri, 09 Aug 2019 13:15:02 GMT'
        reqmock.mockresponse(master_file_path, code=200, data=content1)
        replay(xom, replica_xom)
        assert replication_errors.errors == {}
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
        assert not xom.config.serverdir.join(entry._storepath).exists()

        # and simulate what the master will respond
        xom.httpget.mockresponse(master_file_path, status_code=410)

        # and then we try to see if we can replicate the create and del changes
        replay(xom, replica_xom)

        with replica_xom.keyfs.transaction():
            r_entry = replica_xom.filestore.get_file_entry(entry.relpath)
            assert not r_entry.file_exists()

    def test_fetch_pypi_nomd5(self, gen, patch_reqsessionmock, reqmock, xom, replica_xom):
        (frthread,) = replica_xom.replica_thread.file_replication_threads
        frt_reqmock = patch_reqsessionmock(frthread.session)
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
        frt_reqmock.mockresponse(
            master_file_path, code=500, data=b'')
        with pytest.raises(MissingFileException) as e:
            # the event handling will stop with an exception
            replay(xom, replica_xom)
        assert str(e.value) == "missing file 'root/pypi/+e/https_pypi.org_package_some/some-1.8.zip' at serial 2"
        assert replica_xom.keyfs.get_current_serial() == xom.keyfs.get_current_serial()
        # event handling hasn't progressed
        assert replica_xom.keyfs.notifier.read_event_serial() == 1
        # we also got an error entry
        replication_errors = replica_xom.replica_thread.shared_data.errors
        assert list(replication_errors.errors.keys()) == [
            'root/pypi/+e/https_pypi.org_package_some/some-1.8.zip']

        # now get the real thing
        frt_reqmock.mockresponse(
            master_file_path, code=200, data=content1)
        # wait for the error queue to clear
        replica_xom.replica_thread.wait(error_queue=True)
        # there should be no errors anymore
        assert replication_errors.errors == {}
        # and the file should exist
        with replica_xom.keyfs.transaction():
            assert r_entry.file_exists()
            assert r_entry.file_get_content() == content1
        # and the event handling should continue
        replay(xom, replica_xom)
        # event handling has continued
        assert replica_xom.keyfs.notifier.read_event_serial() == replica_xom.keyfs.get_current_serial()

    def test_cache_remote_file_fails(self, xom, replica_xom, gen,
                                     pypistage, monkeypatch, reqmock):
        from devpi_server.filestore import BadGateway
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
            pypistage.xom.httpget.mockresponse(url, status_code=500)
            with pytest.raises(BadGateway) as e:
                for part in iter_remote_file_replica(replica_xom, entry):
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
            pypistage.xom.httpget.mockresponse(url, status_code=500)
            pypistage.xom.httpget.mockresponse(
                entry.url, headers=headers, content=b'123')
            result = iter_remote_file_replica(replica_xom, entry)
            headers = next(result)
            # there should be one get
            (call_log_entry,) = [
                x for x in pypistage.xom.httpget.call_log
                if x['url'] == url]
            # and it should have an authorization header
            assert call_log_entry['extra_headers']['Authorization'].startswith('Bearer')
            # and UUID header
            assert call_log_entry['extra_headers'][H_REPLICA_UUID]
            assert headers['content-length'] == '3'
            assert b''.join(result) == b'123'

    def test_checksum_mismatch(self, xom, replica_xom, gen, maketestapp,
                               makemapp, patch_reqsessionmock):
        # this test might seem to be doing the same as test_fetch above, but
        # test_fetch creates a new transaction for the same file, which doesn't
        # happen 'in real life'™
        (frthread,) = replica_xom.replica_thread.file_replication_threads
        frt_reqmock = patch_reqsessionmock(frthread.session)
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
        frt_reqmock.mockresponse(master_file_url, code=200, data=b'13')
        replay(xom, replica_xom, events=False)
        replica_xom.replica_thread.wait()
        assert xom.keyfs.get_current_serial() == replica_xom.keyfs.get_current_serial()
        replication_errors = replica_xom.replica_thread.shared_data.errors
        assert list(replication_errors.errors.keys()) == [
            '%s/+f/d0b/425e00e15a0d3/hello-1.0.zip' % api.stagename]
        # the master and replica are in sync, so getting the file on the
        # replica needs to fetch it again
        headers = {"content-length": "8",
                   "last-modified": "Thu, 25 Nov 2010 20:00:27 GMT",
                   "content-type": "application/zip",
                   "X-DEVPI-SERIAL": str(xom.keyfs.get_current_serial())}
        replica_xom.httpget.mockresponse(master_file_url, code=200, content=content1, headers=headers)
        with replica_xom.keyfs.transaction(write=False) as tx:
            assert not tx.conn.io_file_exists(file_relpath)
        r = r_app.get(path)
        assert r.status_code == 200
        assert r.body == content1
        with replica_xom.keyfs.transaction(write=False) as tx:
            assert tx.conn.io_file_exists(file_relpath)
        replication_errors = replica_xom.replica_thread.shared_data.errors
        assert list(replication_errors.errors.keys()) == []


def test_simplelinks_update_updates_projectname(pypistage, replica_xom, xom):
    replica_xom.thread_pool.start_one(replica_xom.replica_thread)
    replica_xom.thread_pool.start_one(
        replica_xom.replica_thread.file_replication_threads[0])
    pypistage.mock_simple_projects([])
    pypistage.mock_simple("pytest", pkgver="pytest-1.0.zip")
    with xom.keyfs.transaction():
        assert not pypistage.list_projects_perstage()

    with xom.keyfs.transaction():
        assert len(pypistage.get_simplelinks("pytest")) == 1

    # replicate including executing events
    replay(xom, replica_xom)

    with replica_xom.keyfs.transaction():
        st = replica_xom.model.getstage(pypistage.name)
        assert st.list_projects_perstage() == set(["pytest"])


def test_get_simplelinks_perstage(httpget, monkeypatch, pypistage, replica_pypistage,
                                  pypiurls, replica_xom, xom):
    replica_xom.thread_pool.start_one(replica_xom.replica_thread)
    replica_xom.thread_pool.start_one(
        replica_xom.replica_thread.file_replication_threads[0])

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
    # there should be one get
    (call_log_entry,) = [
        x for x in pypistage.xom.httpget.call_log
        if x['url'].startswith(pypiurls.simple)]
    # and it should have an authorization header
    assert call_log_entry['extra_headers']['Authorization'].startswith('Bearer')
    # and UUID header
    assert call_log_entry['extra_headers'][H_REPLICA_UUID]

    # now we change the links and expire the cache
    pypiurls.simple = orig_simple
    pypistage.mock_simple("pytest", pkgver="pytest-1.1.zip", pypiserial=10001)
    pypistage.cache_retrieve_times.expire('pytest')
    with xom.keyfs.transaction(write=True):
        pypistage.get_releaselinks("pytest")
    assert xom.keyfs.get_current_serial() > serial

    # we patch wait_tx_serial so we can check it
    orig_wait_tx_serial = replica_xom.keyfs.wait_tx_serial
    called = []

    def wait_tx_serial(serial, timeout=None):
        result = orig_wait_tx_serial(serial, timeout=timeout)
        called.append((serial, result))
        return result

    monkeypatch.setattr(replica_xom.keyfs, 'wait_tx_serial', wait_tx_serial)
    replay(xom, replica_xom, events=False)
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
    assert called == [(2, True)]
    replay(xom, replica_xom)
    assert len(ret) == 1
    assert ret[0].relpath == 'root/pypi/+e/https_pypi.org_pytest/pytest-1.1.zip'


def test_replicate_deleted_user(mapp, replica_xom):
    replica_xom.thread_pool.start_one(replica_xom.replica_thread)
    replica_xom.thread_pool.start_one(
        replica_xom.replica_thread.file_replication_threads[0])
    mapp.create_and_use("hello/dev")
    content = mapp.makepkg("hello-1.0.tar.gz", b"content", "hello", "1.0")
    mapp.upload_file_pypi("hello-1.0.tar.gz", content, "hello", "1.0")
    mapp.delete_user("hello")
    # replicate the state
    replay(mapp.xom, replica_xom)
    # create again
    mapp.create_and_use("hello/dev")
    # replicate the state again
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
    assert len(calls) == 0
    assert r.json['result']['authstatus'] == ['noauth', '', []]


def test_master_url_auth(makexom, monkeypatch):
    from devpi_server.mythread import Shutdown
    replica_xom = makexom(opts=["--master=http://foo:pass@localhost"])
    assert replica_xom.config.master_auth == ("foo", "pass")
    assert replica_xom.config.master_url.url == "http://localhost"
    replica_xom.create_app()

    results = []

    def get(*args, **kwargs):
        results.append((args, kwargs))
        replica_xom.thread_pool.shutdown()

    monkeypatch.setattr(replica_xom.replica_thread.session, "get", get)
    with pytest.raises(Shutdown):
        replica_xom.replica_thread.thread_run()
    assert results[0][1]['auth'] == ("foo", "pass")


def test_master_url_auth_with_port(makexom):
    replica_xom = makexom(opts=["--master=http://foo:pass@localhost:3140"])
    assert replica_xom.config.master_auth == ("foo", "pass")
    assert replica_xom.config.master_url.url == "http://localhost:3140"


def test_replica_user_auth_before_other_plugins(makexom):
    from devpi_server import replica
    from devpi_server.config import hookimpl
    from devpi_server.auth import Auth
    from pyramid.httpexceptions import HTTPForbidden

    class Plugin:
        @hookimpl
        def devpiserver_auth_request(self, request, userdict, username, password):
            raise RuntimeError("Shouldn't be called")

        @hookimpl
        def devpiserver_auth_user(self, userdict, username, password):
            raise RuntimeError("Shouldn't be called")

    plugin = Plugin()
    # register both plugins, so the above plugin would normally be called first
    xom = makexom(plugins=[replica, plugin])
    auth = Auth(xom.model, "qweqwe")
    with xom.keyfs.transaction(write=False):
        # because the replica auth has tryfirst our plugin shouldn't be called
        with pytest.raises(HTTPForbidden):
            auth._get_auth_status(replica.REPLICA_USER_NAME, '')


class TestFileReplicationSharedData:
    @pytest.fixture
    def shared_data(self, replica_xom):
        from devpi_server.replica import FileReplicationSharedData
        # allow on_import to run right away, so we don't need to rely
        # on the initial import thread for tests
        replica_xom.replica_thread.replica_in_sync_at = 0
        return FileReplicationSharedData(replica_xom)

    def test_mirror_priority(self, shared_data):
        result = []

        mirror_file = 'root/pypi/+f/3f8/3058ac9076112/pytest-2.0.0.zip'
        stage_file = 'root/dev/+f/274/e88b0b3d028fe/pytest-2.1.0.zip'
        # set the index_types cache to prevent db access
        shared_data.index_types.put('root/pypi', 'mirror')
        shared_data.index_types.put('root/dev', 'stage')

        def handler(is_from_mirror, serial, key, keyname, value, back_serial):
            result.append(key)
        # Regardless of the serial or add order, the stage should come first
        cases = [
            ((mirror_file, 0), (stage_file, 0)),
            ((mirror_file, 1), (stage_file, 0)),
            ((mirror_file, 0), (stage_file, 1)),
            ((stage_file, 0), (mirror_file, 0)),
            ((stage_file, 1), (mirror_file, 0)),
            ((stage_file, 0), (mirror_file, 1))]
        for (relpath1, serial1), (relpath2, serial2) in cases:
            key1 = shared_data.xom.keyfs.get_key_instance('STAGEFILE', relpath1)
            key2 = shared_data.xom.keyfs.get_key_instance('STAGEFILE', relpath2)
            shared_data.on_import(None, serial1, key1, None, -1)
            shared_data.on_import(None, serial2, key2, None, -1)
            assert shared_data.queue.qsize() == 2
            shared_data.process_next(handler)
            shared_data.process_next(handler)
            assert shared_data.queue.qsize() == 0
            assert result == [stage_file, mirror_file]
            result.clear()

    @pytest.mark.parametrize("index_type", ["mirror", "stage"])
    def test_serial_priority(self, index_type, shared_data):
        relpath = 'root/dev/+f/274/e88b0b3d028fe/pytest-2.1.0.zip'
        key = shared_data.xom.keyfs.get_key_instance('STAGEFILE', relpath)
        # set the index_types cache to prevent db access
        shared_data.index_types.put('root/dev', 'stage')
        result = []

        def handler(is_from_mirror, serial, key, keyname, value, back_serial):
            result.append(serial)

        # Later serials come first
        shared_data.on_import(None, 1, key, None, -1)
        shared_data.on_import(None, 100, key, None, -1)
        shared_data.on_import(None, 10, key, None, -1)
        assert shared_data.queue.qsize() == 3
        shared_data.process_next(handler)
        shared_data.process_next(handler)
        shared_data.process_next(handler)
        assert shared_data.queue.qsize() == 0
        assert result == [100, 10, 1]

    def test_error_queued(self, shared_data):
        relpath = 'root/dev/+f/274/e88b0b3d028fe/pytest-2.1.0.zip'
        key = shared_data.xom.keyfs.get_key_instance('STAGEFILE', relpath)
        # set the index_types cache to prevent db access
        shared_data.index_types.put('root/dev', 'stage')

        next_ts_result = []
        handler_result = []
        orig_next_ts = shared_data.next_ts

        def next_ts(delay):
            next_ts_result.append(delay)
            return orig_next_ts(delay)
        shared_data.next_ts = next_ts

        def handler(is_from_mirror, serial, key, keyname, value, back_serial):
            handler_result.append(key)
            raise ValueError

        # No waiting on empty queues
        shared_data.QUEUE_TIMEOUT = 0
        shared_data.on_import(None, 0, key, None, -1)
        assert shared_data.queue.qsize() == 1
        assert shared_data.error_queue.qsize() == 0
        assert next_ts_result == []
        assert handler_result == []
        # An exception puts the info into the error queue
        shared_data.process_next(handler)
        assert shared_data.queue.qsize() == 0
        assert shared_data.error_queue.qsize() == 1
        assert next_ts_result == [11]
        assert handler_result == [relpath]
        # Calling again doesn't change anything,
        # because there is a delay on errors
        shared_data.process_next(handler)
        assert shared_data.queue.qsize() == 0
        assert shared_data.error_queue.qsize() == 1
        assert next_ts_result == [11]
        assert handler_result == [relpath]
        # When removing the delay check, the handler is called again and the
        # info re-queued with a longer delay
        shared_data.is_in_future = lambda ts: False
        shared_data.process_next(handler)
        assert shared_data.queue.qsize() == 0
        assert shared_data.error_queue.qsize() == 1
        assert next_ts_result == [11, 11 * shared_data.ERROR_QUEUE_DELAY_MULTIPLIER]
        assert handler_result == [relpath, relpath]
        while 1:
            # The delay is increased until reaching a maximum
            shared_data.process_next(handler)
            delay = next_ts_result[-1]
            if delay >= shared_data.ERROR_QUEUE_MAX_DELAY:
                break
        # then it will stay there
        shared_data.process_next(handler)
        delay = next_ts_result[-1]
        assert delay == shared_data.ERROR_QUEUE_MAX_DELAY
        # The number of retries should be reasonable.
        # Needs adjustment in case the ERROR_QUEUE_DELAY_MULTIPLIER
        # or ERROR_QUEUE_MAX_DELAY is changed
        assert len(next_ts_result) == 17
        assert len(handler_result) == 17
