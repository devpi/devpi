from .functional import TestProjectThings as BaseTestProjectThings
from .functional import TestUserThings as BaseTestUserThings
from .functional import TestIndexThings as BaseTestIndexThings
from .functional import TestIndexPushThings as BaseTestIndexPushThings
from .functional import TestMirrorIndexThings as BaseTestMirrorIndexThings
import pytest


@pytest.fixture
def mapp(makemapp, nginx_host_port, secretfile):
    app = makemapp(options=[
        '--master', 'http://%s:%s' % nginx_host_port,
        '--secretfile', secretfile.strpath])
    app.xom.thread_pool.start_one(app.xom.replica_thread)
    try:
        yield app
    finally:
        app.xom.thread_pool.shutdown()


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
