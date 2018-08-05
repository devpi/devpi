# this file is shared via symlink with devpi-client,
# so for the time being it must continue to work with Python 2
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.response import HTTPResponse
import fnmatch
import pytest
import py


@pytest.fixture
def reqmock(monkeypatch):
    mr = mocked_request()

    def get_adapter(self, url):
        return MockAdapter(mr, url)

    monkeypatch.setattr("requests.sessions.Session.get_adapter", get_adapter)
    return mr


@pytest.fixture
def patch_reqsessionmock(monkeypatch):
    def patch_reqsessionmock(session):
        mr = mocked_request()

        def get_adapter(self, url):
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

    def process_request(self, request, kwargs):
        url = request.url
        response = self.url2reply.get((url, request.method))
        if response is None:
            response = self.url2reply.get((url, None))
            if response is None:
                for (name, method), response in self.url2reply.items():
                    if method is None or method == request.method:
                        if fnmatch.fnmatch(request.url, name):
                            break
                else:
                    raise Exception("not mocked call to %s" % url)
        response.add_request(request)
        r = HTTPAdapter().build_response(request, response)
        return r

    def mockresponse(self, url, code, method=None, data=None, headers=None,
                     on_request=None, reason=None):
        if not url:
            url = "*"
        r = ReqReply(code=code, data=data, headers=headers,
                     on_request=on_request, reason=reason)
        if method is not None:
            method = method.upper()
        self.url2reply[(url, method)] = r
        return r
    mock = mockresponse


class ReqReply(HTTPResponse):
    def __init__(self, code, data, headers, on_request, reason=None):
        if py.builtin._istext(data):
            data = data.encode("utf-8")
        super(ReqReply, self).__init__(body=py.io.BytesIO(data),
                                       status=code,
                                       headers=headers,
                                       reason=reason,
                                       preload_content=False)
        self.requests = []
        self.on_request = on_request

    def add_request(self, request):
        if self.on_request:
            self.on_request(request)
        self.requests.append(request)
