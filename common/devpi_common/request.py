import sys
from requests import *  # noqa
from requests.exceptions import ConnectionError, RequestException, BaseHTTPError

def new_requests_session(agent=None):
    if agent is None:
        agent = "devpi"
    else:
        agent = "devpi-%s/%s" % agent
    agent += " (py%s; %s)" % (sys.version.split()[0], sys.platform)
    session = Session()
    session.headers["user-agent"] = agent
    session.ConnectionError = ConnectionError
    session.RequestException = RequestException
    session.Errors = (RequestException, BaseHTTPError)
    return session
