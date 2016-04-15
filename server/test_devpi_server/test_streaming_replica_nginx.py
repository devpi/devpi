import pytest
from . import test_streaming


@pytest.fixture
def host_port(nginx_replica_host_port):
    return nginx_replica_host_port


@pytest.fixture
def files_directory(server_directory):
    return server_directory.join('replica', '+files')


server_url_session = test_streaming.server_url_session
content_digest = test_streaming.content_digest


for attr in dir(test_streaming):
    if attr.startswith('test_'):
        globals()[attr] = getattr(test_streaming, attr)
