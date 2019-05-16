import pytest
import sys
from . import test_streaming


pytestmark = [
    pytest.mark.skipif(
        sys.platform == "win32",
        reason="issues with process management on Windows"),
    pytest.mark.skipif("not config.option.slow")]


@pytest.fixture
def host_port(nginx_host_port):
    return nginx_host_port


@pytest.fixture
def files_directory(server_directory):
    return server_directory.join('master', '+files')


server_url_session = test_streaming.server_url_session
content_digest = test_streaming.content_digest


for attr in dir(test_streaming):
    if attr.startswith(('test_', 'Test')):
        globals()[attr] = getattr(test_streaming, attr)
