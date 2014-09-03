import sys
import requests
import pytest
from devpi_common.request import new_requests_session

def test_env(monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", "http://this")
    monkeypatch.setenv("HTTPS_PROXY", "http://that")
    session = new_requests_session()
    with pytest.raises(requests.exceptions.RequestException):
        session.get("http://example.com")

def test_useragent():
    s = new_requests_session(agent=("hello", "1.2"))
    ua = s.headers["user-agent"]
    assert "devpi-hello/1.2" in ua
    assert sys.version.split()[0] in ua
    assert "*" not in ua

def test_exception_attributes():
    session = new_requests_session()
    assert isinstance(session.Errors, tuple)
