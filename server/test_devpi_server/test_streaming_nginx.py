from . import test_streaming
import pytest
import sys


pytestmark = [
    pytest.mark.skipif(
        sys.platform == "win32",
        reason="issues with process management on Windows"),
    pytest.mark.slow]


@pytest.fixture
def host_port(nginx_host_port):
    return nginx_host_port


@pytest.fixture
def files_path(primary_server_path):
    return primary_server_path / '+files'


server_url_session = test_streaming.server_url_session
content_digest = test_streaming.content_digest


for attr in dir(test_streaming):
    if attr.startswith(('test_', 'Test')):
        globals()[attr] = getattr(test_streaming, attr)
