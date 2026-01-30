from .functional import TestIndexPushThings as BaseTestIndexPushThings
from .functional import TestIndexThings as BaseTestIndexThings
from .functional import TestMirrorIndexThings as BaseTestMirrorIndexThings
from .functional import TestProjectThings as BaseTestProjectThings
from .functional import TestUserThings as BaseTestUserThings
import pytest
import time


@pytest.fixture
def replica_mapp(makemapp, primary_host_port, secretfile):
    app = makemapp(options=[
        '--primary-url', 'http://%s:%s' % primary_host_port,
        '--secretfile', secretfile])
    try:
        yield app
    finally:
        app.xom.thread_pool.kill()


@pytest.fixture
def mapp(replica_mapp):
    replica_mapp.xom.thread_pool.start_one(replica_mapp.xom.replica_thread)
    return replica_mapp


@pytest.mark.slow
class TestProjectThings(BaseTestProjectThings):
    pass


@pytest.mark.slow
class TestUserThings(BaseTestUserThings):
    pass


@pytest.mark.slow
class TestIndexThings(BaseTestIndexThings):
    pass


@pytest.mark.slow
class TestIndexPushThings(BaseTestIndexPushThings):
    pass


@pytest.mark.slow
class TestMirrorIndexThings(BaseTestMirrorIndexThings):
    pass


@pytest.mark.slow
@pytest.mark.nomocking
@pytest.mark.storage_with_filesystem
def test_replicating_deleted_pypi_release(
        makemapp, makefunctionaltestapp,
        primary_host_port, primary_server_path,
        replica_mapp, simpypi):
    # this was the behavior of devpi-server 4.3.1:
    # - a release was mirrored from pypi
    # - at some point the locally cached file was removed from the filesystem
    # - the release/project was removed from pypi
    # - a new replica tries to fetch the file, because it's still
    #   mentioned in the changelog
    # - the master tries to download it from pypi and gets a 404
    # - the master replies with a 502 and the replica stops at this point
    from devpi_common.url import URL
    mapp = makemapp(makefunctionaltestapp(primary_host_port))
    content = b'13'
    simpypi.add_release('pkg', pkgver='pkg-1.0.zip')
    simpypi.add_file('/pkg/pkg-1.0.zip', content)
    mapp.create_and_login_user('mirror')
    indexconfig = dict(
        type="mirror",
        mirror_url=simpypi.simpleurl,
        mirror_cache_expiry=0)
    mapp.create_index("mirror", indexconfig=indexconfig)
    mapp.use("mirror/mirror")
    result = mapp.getreleaseslist("pkg")
    assert len(result) == 1
    r = mapp.downloadrelease(200, result[0])
    assert r == content
    # remove files
    relpath = URL(result[0]).path[1:]
    path = primary_server_path / '+files' / relpath
    tries = 0
    while not path.exists() and tries < 10:
        time.sleep(.1)
        tries += 1
    path.unlink()
    simpypi.remove_file('/pkg/pkg-1.0.zip')
    mapp.delete_index("mirror")
    # now start the replication thread
    master_serial = mapp.getjson('/+status')['result']['serial']
    replica_mapp.xom.thread_pool.start_one(replica_mapp.xom.replica_thread)
    replica_mapp.xom.keyfs.wait_tx_serial(master_serial)
    # the replica is in sync
    assert replica_mapp.xom.keyfs.get_current_serial() == master_serial


@pytest.mark.slow
@pytest.mark.nomocking
def test_frt_exception_handling(
    makefunctionaltestapp,
    makemapp,
    makexom,
    mock,
    monkeypatch,
    primary_host_port,
    secretfile,
):
    import httpx

    replica_xom = makexom(
        [
            "--primary-url",
            "http://%s:%s" % primary_host_port,
            "--file-replication-threads",
            "1",
            "--secretfile",
            secretfile,
        ]
    )
    mapp = makemapp(makefunctionaltestapp(primary_host_port))
    # shorten delays for tests
    replica_xom.replica_thread.shared_data.QUEUE_TIMEOUT = 0.1
    replica_xom.replica_thread.shared_data.ERROR_QUEUE_MAX_DELAY = 0.1
    replica_xom.replica_thread.shared_data.ERROR_QUEUE_REPORT_DELAY = 0
    (replica_xom.frt,) = replica_xom.replica_thread.file_replication_threads
    mapp.create_and_use()
    content1 = mapp.makepkg("hello-1.0.zip", b"content1", "hello", "1.0")
    mapp.upload_file_pypi("hello-1.0.zip", content1, "hello", "1.0")
    replica_xom.thread_pool.start_one(replica_xom.replica_thread)
    tries = 0
    while (
        replica_xom.replica_thread.replica_metadata_in_sync_at is None and tries < 100
    ):
        time.sleep(0.1)
        tries += 1
    # test exception during initial connection
    with monkeypatch.context() as m:
        stream_mock = mock.Mock()
        stream_mock.side_effect = httpx.RemoteProtocolError("foo")
        m.setattr(replica_xom.frt.http.http.client, "stream", stream_mock)
        assert not replica_xom.frt.shared_data.queue.empty()
        assert replica_xom.frt.shared_data.error_queue.empty()
        replica_xom.frt.shared_data.process_next(replica_xom.frt.handler)
        assert replica_xom.frt.shared_data.queue.empty()
        assert replica_xom.frt.shared_data.queue.unfinished_tasks == 0
        assert not replica_xom.frt.shared_data.error_queue.empty()
        assert replica_xom.frt.shared_data.error_queue.unfinished_tasks == 1
        ((k, v),) = replica_xom.frt.shared_data.errors.errors.items()
        assert "hello-1.0.zip" in k
        assert "foo" in v["message"]
    # test exception during streaming
    with monkeypatch.context() as m:
        streamer_iter_mock = mock.Mock()
        streamer_iter_mock.side_effect = httpx.RemoteProtocolError("foo")
        m.setattr("devpi_server.views.FileStreamer.__iter__", streamer_iter_mock)
        replica_xom.frt.shared_data.process_next(replica_xom.frt.handler)
        assert replica_xom.frt.shared_data.queue.empty()
        assert replica_xom.frt.shared_data.queue.unfinished_tasks == 0
        assert not replica_xom.frt.shared_data.error_queue.empty()
        assert replica_xom.frt.shared_data.error_queue.unfinished_tasks == 1
        ((k, v),) = replica_xom.frt.shared_data.errors.errors.items()
        assert "hello-1.0.zip" in k
        assert "foo" in v["message"]
    # now with no errors
    replica_xom.frt.shared_data.process_next(replica_xom.frt.handler)
    assert replica_xom.frt.shared_data.queue.empty()
    assert replica_xom.frt.shared_data.queue.unfinished_tasks == 0
    assert replica_xom.frt.shared_data.error_queue.empty()
    assert replica_xom.frt.shared_data.error_queue.unfinished_tasks == 0
    assert replica_xom.frt.shared_data.errors.errors == {}
