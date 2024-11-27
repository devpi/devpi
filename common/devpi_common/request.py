from requests import Session
from requests.adapters import HTTPAdapter
from urllib3.exceptions import HTTPError as BaseHTTPError
import requests.exceptions as request_exceptions
import sys


class RetrySession(Session):
    def __init__(self, max_retries):
        super(RetrySession, self).__init__()
        if max_retries is not None:
            self.mount('https://', HTTPAdapter(max_retries=max_retries))
            self.mount('http://', HTTPAdapter(max_retries=max_retries))


def new_requests_session(agent=None, max_retries=None):
    if agent is None:
        agent = "devpi"
    else:
        agent = "devpi-%s/%s" % agent
    agent += " (py%s; %s)" % (sys.version.split()[0], sys.platform)
    session = RetrySession(max_retries)
    session.headers["user-agent"] = agent
    session.ConnectionError = ConnectionError  # type: ignore[attr-defined]
    session.RequestException = request_exceptions.RequestException  # type: ignore[attr-defined]
    session.Errors = (request_exceptions.RequestException, BaseHTTPError)  # type: ignore[attr-defined]
    session.SSLError = request_exceptions.SSLError  # type: ignore[attr-defined]
    return session
