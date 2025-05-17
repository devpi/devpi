# this file is shared via symlink with devpi-client,
# so it must continue to work with the lowest supported Python 3.x version
from io import BytesIO
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.response import HTTPResponse
import fnmatch
import pytest


@pytest.fixture
def reqmock(monkeypatch):
    mr = mocked_request()

    def get_adapter(self, url):  # noqa: ARG001
        return MockAdapter(mr, url)

    monkeypatch.setattr("requests.sessions.Session.get_adapter", get_adapter)
    return mr


@pytest.fixture
def patch_reqsessionmock(monkeypatch):
    def patch_reqsessionmock(session):
        mr = mocked_request()

        def get_adapter(self, url):  # noqa: ARG001
            return MockAdapter(mr, url)

        monkeypatch.setattr(session, "get_adapter", get_adapter.__get__(session))
        return mr

    return patch_reqsessionmock


class MockAdapter:
    def __init__(self, mock_request, url):
        self.url = url
        self.mock_request = mock_request

    def send(self, request, **kwargs):
        return self.mock_request.process_request(request, kwargs)


class mocked_request:
    def __init__(self):
        self.url2reply = {}

    def get_response(self, request):
        url = request.url
        response = self.url2reply.get((url, request.method))
        if response is not None:
            return response
        response = self.url2reply.get((url, None))
        if response is not None:
            return response
        for (name, method), response in self.url2reply.items():
            if method not in (None, request.method):
                continue
            if fnmatch.fnmatch(request.url, name):
                return response
        raise Exception("not mocked call to %s" % url)  # noqa: TRY002

    def process_request(self, request, kwargs):  # noqa: ARG002
        response = self.get_response(request)
        response.add_request(request)
        return HTTPAdapter().build_response(request, response.make())

    def mockresponse(
        self,
        url,
        code,
        method=None,
        data=None,
        headers=None,
        on_request=None,
        reason=None,
    ):
        if not url:
            url = "*"
        r = ReplyMaker(
            code=code, data=data, headers=headers, on_request=on_request, reason=reason
        )
        if method is not None:
            method = method.upper()
        self.url2reply[(url, method)] = r
        return r

    mock = mockresponse


class ReplyMaker:
    def __init__(self, code, data, headers, on_request, reason=None):
        if isinstance(data, str):
            data = data.encode("utf-8")
        self.data = data
        self.requests = []
        self.on_request = on_request
        self.kwargs = dict(status=code, headers=headers, reason=reason)

    def add_request(self, request):
        if self.on_request:
            self.on_request(request)
        self.requests.append(request)

    def make(self):
        return HTTPResponse(
            body=BytesIO(self.data), preload_content=False, **self.kwargs
        )
