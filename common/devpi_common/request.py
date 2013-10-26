import sys
from requests import *  # noqa
from requests.exceptions import ConnectionError, RequestException

try:
    from urllib.request import getproxies
except ImportError:
    from urllib import getproxies

def new_requests_session(proxies=True, agent=None):
    if agent is None:
        agent = "devpi"
    else:
        agent = "devpi-%s/%s" % agent
    agent += " (py%s; %s)" % (sys.version.split()[0], sys.platform)
    session = Session()
    session.headers["user-agent"] = agent
    if proxies:
        session.proxies = getproxies()
    session.ConnectionError = ConnectionError
    session.RequestException = RequestException
    return session
