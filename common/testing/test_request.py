import logging
import sys
import requests
import pytest
from devpi_common.request import new_requests_session

class CountRetryHandler(logging.Handler):
    def __init__(self):
        super(CountRetryHandler, self).__init__()
        self.count = 0

    def filter(self, record):
        if record.msg.startswith('Retrying'):
            return 1
        return 0

    def emit(self, record):
        self.count += 1

@pytest.fixture
def retry_counter():
    log = logging.getLogger('requests.packages.urllib3.connectionpool')
    previous_level = log.getEffectiveLevel()

    # Configure logging to report retry attempts
    log.setLevel(logging.WARNING)
    _retry_counter = CountRetryHandler()
    log.addHandler(_retry_counter)
    yield _retry_counter

    # restore logging
    log.removeHandler(_retry_counter)
    log.setLevel(previous_level)

@pytest.mark.parametrize('max_retries', [
    None,
    0,
    2,
])
def test_env(monkeypatch, max_retries, retry_counter):
    monkeypatch.setenv("HTTP_PROXY", "http://this")
    monkeypatch.setenv("HTTPS_PROXY", "http://that")
    session = new_requests_session(max_retries=max_retries)
    with pytest.raises(requests.exceptions.RequestException):
        session.get("http://example.com")

    assert retry_counter.count == (max_retries or 0)

def test_useragent():
    s = new_requests_session(agent=("hello", "1.2"))
    ua = s.headers["user-agent"]
    assert "devpi-hello/1.2" in ua
    assert sys.version.split()[0] in ua
    assert "*" not in ua

def test_exception_attributes():
    session = new_requests_session()
    assert isinstance(session.Errors, tuple)
