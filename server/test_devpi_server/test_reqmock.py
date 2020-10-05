from __future__ import unicode_literals

import pytest
import requests


@pytest.mark.parametrize("method", [None, "get", "post"])
def test_req(reqmock, method):
    mr = reqmock.mockresponse("http://heise.de/", 201, data="hello",
                         method=method,
                         headers={"content-type": "text/plain"})
    r = requests.request(method or "GET", "http://heise.de")
    assert r.status_code == 201
    assert len(mr.requests) == 1
    assert r.content == b"hello"


def test_req_diff(reqmock):
    mr = reqmock.mockresponse("http://heise.de/", 201, data="hello",
                         method="GET",
                         headers={"content-type": "text/plain"})
    mr2 = reqmock.mockresponse("http://heise.de/", 200, data="world",
                         method="POST",
                         headers={"content-type": "text/plain"})
    r = requests.request("GET", "http://heise.de")
    assert r.content == b"hello"
    assert r.status_code == 201
    r = requests.request("POST", "http://heise.de")
    assert r.content == b"world"
    assert r.status_code == 200
    assert len(mr.requests) == 1
    assert len(mr2.requests) == 1


def test_req_func(reqmock):
    l = []
    mr = reqmock.mockresponse("http://heise.de/", 201, data="hello",
                         method="GET", on_request=lambda x: l.append(x),
                         headers={"content-type": "text/plain"})
    r = requests.get("http://heise.de/")
    assert l == mr.requests
    assert r.status_code == 201


def test_req_glob(reqmock):
    mr = reqmock.mockresponse("http://heise.de*", 201, data="hello",
                         headers={"content-type": "text/plain"})
    r = requests.get("http://heise.de/index.html")
    assert r.status_code == 201
    assert mr.requests[0].url == "http://heise.de/index.html"
