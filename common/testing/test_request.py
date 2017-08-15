import sys
import requests
import pytest
from devpi_common.request import new_requests_session


@pytest.mark.parametrize('max_retries', [
    None,
    0,
    2,
])
def test_env(monkeypatch, max_retries):
    from urllib3.util.retry import Retry
    monkeypatch.setenv("HTTP_PROXY", "http://this")
    monkeypatch.setenv("HTTPS_PROXY", "http://that")
    orig_increment = Retry.increment
    increment_retry_totals = []

    def increment(self, *args, **kwargs):
        increment_retry_totals.append(self.total)
        return orig_increment(self, *args, **kwargs)

    monkeypatch.setattr(Retry, "increment", increment)
    session = new_requests_session(max_retries=max_retries)
    with pytest.raises(requests.exceptions.RequestException):
        session.get("http://example.com")
    assert tuple(increment_retry_totals) in ((0,), (2, 1, 0))


def test_useragent():
    s = new_requests_session(agent=("hello", "1.2"))
    ua = s.headers["user-agent"]
    assert "devpi-hello/1.2" in ua
    assert sys.version.split()[0] in ua
    assert "*" not in ua

def test_exception_attributes():
    session = new_requests_session()
    assert isinstance(session.Errors, tuple)
