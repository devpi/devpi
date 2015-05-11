from pyramid.authentication import b64decode
import binascii


def devpiserver_get_credentials(request):
    """Extracts username and password from X-Devpi-Auth header.

    Returns a tuple with (username, password) if credentials could be
    extracted, or None if no credentials were found.
    """
    auth = request.headers.get('X-Devpi-Auth')
    if not auth:
        return None
    try:
        authbytes = b64decode(auth.strip())
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
