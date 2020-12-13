from .functional import TestUserThings as BaseTestUserThings
from .functional import TestIndexThings as BaseTestIndexThings
from .functional import TestIndexPushThings as BaseTestIndexPushThings
from .functional import TestMirrorIndexThings as BaseTestMirrorIndexThings
import pytest


@pytest.fixture
def replica_mapp(makemapp, master_host_port, secretfile):
    app = makemapp(options=[
        '--master', 'http://%s:%s' % master_host_port,
        '--secretfile', secretfile.strpath])
    try:
        yield app
    finally:
        app.xom.thread_pool.shutdown()


@pytest.fixture
def mapp(replica_mapp):
    replica_mapp.xom.thread_pool.start_one(replica_mapp.xom.replica_thread)
    return replica_mapp


@pytest.mark.skipif("not config.option.slow")
class TestUserThings(BaseTestUserThings):
    pass


@pytest.mark.skipif("not config.option.slow")
class TestIndexThings(BaseTestIndexThings):
    pass


@pytest.mark.skipif("not config.option.slow")
class TestIndexPushThings(BaseTestIndexPushThings):
    pass


@pytest.mark.skipif("not config.option.slow")
class TestMirrorIndexThings(BaseTestMirrorIndexThings):
    pass


@pytest.mark.skipif("not config.option.slow")
@pytest.mark.nomocking
@pytest.mark.storage_with_filesystem
def test_replicating_deleted_pypi_release(
        caplog, makemapp, makefunctionaltestapp,
        master_host_port, master_serverdir,
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
    import time
    mapp = makemapp(makefunctionaltestapp(master_host_port))
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
    path = master_serverdir.join('+files').join(relpath)
    tries = 0
    while not path.exists() and tries < 10:
        time.sleep(.1)
        tries += 1
    path.remove()
    simpypi.remove_file('/pkg/pkg-1.0.zip')
    mapp.delete_index("mirror")
    # now start the replication thread
    master_serial = mapp.getjson('/+status')['result']['serial']
    replica_mapp.xom.thread_pool.start_one(replica_mapp.xom.replica_thread)
    replica_mapp.xom.keyfs.wait_tx_serial(master_serial)
    # the replica is in sync
    assert replica_mapp.xom.keyfs.get_current_serial() == master_serial
