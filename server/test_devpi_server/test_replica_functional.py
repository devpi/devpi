from .functional import TestUserThings as BaseTestUserThings
from .functional import TestIndexThings as BaseTestIndexThings
from .functional import TestMirrorIndexThings as BaseTestMirrorIndexThings
import pytest


@pytest.yield_fixture
def mapp(makemapp, master_host_port):
    from devpi_server.replica import ReplicaThread
    app = makemapp(options=['--master', 'http://%s:%s' % master_host_port])
    rt = ReplicaThread(app.xom)
    app.xom.replica_thread = rt
    app.xom.thread_pool.register(rt)
    app.xom.thread_pool.start_one(rt)
    try:
        yield app
    finally:
        app.xom.thread_pool.shutdown()


@pytest.fixture(autouse=True)
def xfail_hanging_tests(request):
    hanging_tests = set([
        'test_push_existing_to_nonvolatile',
        'test_push_existing_to_volatile'])
    if request.function.__name__  in hanging_tests:
        pytest.xfail(reason="test hanging with replica-setup")


@pytest.mark.skipif("not config.option.slow")
class TestUserThings(BaseTestUserThings):
    pass


@pytest.mark.skipif("not config.option.slow")
class TestIndexThings(BaseTestIndexThings):
    pass


@pytest.mark.skipif("not config.option.slow")
class TestMirrorIndexThings(BaseTestMirrorIndexThings):
    pass
