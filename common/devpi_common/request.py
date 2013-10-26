
from requests import *
from requests.exceptions import ConnectionError, RequestException

try:
    from urllib.request import getproxies
except ImportError:
    from urllib import getproxies

def new_requests_session(proxies=True):
    session = Session()
    if proxies:
        session.proxies = getproxies()
    session.ConnectionError = ConnectionError
    session.RequestException = RequestException
    return session
