from devpi_server.config import hookimpl
from pyramid.authentication import b64decode
import binascii


@hookimpl
def devpiserver_get_credentials(request):
    """Extracts username and password from Authentication header.

    Returns a tuple with (username, password) if credentials could be
    extracted, or None if no credentials were found.
    """
    # support basic authentication for setup.py upload/register
    # the DummyRequest class used in testing doesn't have the attribute
    authorization = request.authorization
    if not authorization:
        return None
    if request.authorization.authtype.lower() != 'basic':
        return None

    try:
        authbytes = b64decode(request.authorization.params)
    except (TypeError, binascii.Error):  # can't decode
        return None

    # try utf-8 first, then latin-1; see discussion in
    # https://github.com/Pylons/pyramid/issues/898
    try:
        auth = authbytes.decode('utf-8')
    except UnicodeDecodeError:
        auth = authbytes.decode('latin-1')

    try:
        username, password = auth.split(':', 1)
    except ValueError:  # not enough values to unpack
        return None
    return username, password
