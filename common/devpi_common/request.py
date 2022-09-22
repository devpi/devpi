import sys
from requests import Session
from requests.adapters import HTTPAdapter
from requests.exceptions import ConnectionError, RequestException, SSLError
from urllib3.exceptions import HTTPError as BaseHTTPError


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
    session.ConnectionError = ConnectionError
    session.RequestException = RequestException
    session.Errors = (RequestException, BaseHTTPError)
    session.SSLError = SSLError
    return session
