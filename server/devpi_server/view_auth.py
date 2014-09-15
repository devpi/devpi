from devpi_common.types import ensure_unicode
from devpi_server.auth import Auth
from devpi_server.views import abort, abort_authenticate
from pyramid.authentication import CallbackAuthenticationPolicy, b64decode
from pyramid.decorator import reify
from pyramid.security import Allow, Deny, Everyone
import binascii


class RootFactory(object):
    def __init__(self, request):
        self.request = request
        self.model = request.registry['xom'].model

    @reify
    def matchdict(self):
        result = {}
        if not self.request.matchdict:
            return result
        for k, v in self.request.matchdict.items():
            if hasattr(v, 'rstrip'):
                v = v.rstrip('/')
            result[k] = v
        return result

    def __acl__(self):
        acl = []
        acl.extend([
            (Allow, 'root', 'user_delete'),
            (Allow, 'root', 'user_modify'),
            (Allow, 'root', 'index_create'),
            (Allow, 'root', 'index_modify'),
            (Allow, 'root', 'index_delete'),
            (Allow, 'root', 'del_project')])
        if self.username == 'root':
            acl.append((Deny, Everyone, 'user_delete'))
        if self.username:
            acl.extend([
                (Allow, self.username, 'user_delete'),
                (Allow, self.username, 'user_modify'),
                (Allow, self.username, 'index_create')])
        stage = None
        if self.username and self.index:
            stage = self.model.getstage(self.username, self.index)
        if stage:
            for principal in stage.ixconfig.get("acl_upload", []):
                if principal == ':ANONYMOUS:':
                    principal = Everyone
                acl.append((Allow, principal, 'pypi_submit'))
            acl.extend([
                (Allow, self.username, 'index_modify'),
                (Allow, self.username, 'index_delete'),
                (Allow, self.username, 'del_project')])
        return acl

    def getstage(self, user, index):
        stage = self.model.getstage(user, index)
        if not stage:
            abort(self.request, 404, "no stage %s/%s" % (user, index))
        return stage

    @reify
    def index(self):
        return self.matchdict.get('index')

    @reify
    def name(self):
        return ensure_unicode(self.matchdict.get('name'))

    @reify
    def version(self):
        return ensure_unicode(self.matchdict.get('version'))

    @reify
    def stage(self):
        return self.getstage(self.username, self.index)

    @reify
    def user(self):
        user = self.model.get_user(self.username)
        if not user:
            abort(self.request, 404, "no user %r" % self.username)
        return user

    @reify
    def username(self):
        return self.matchdict.get('user')


class DevpiAuthenticationPolicy(CallbackAuthenticationPolicy):
    def __init__(self, xom):
        self.realm = "pypi"
        self.auth = Auth(xom.model, xom.config.secret)

    def unauthenticated_userid(self, request):
        """ The userid parsed from the ``Authorization`` request header."""
        credentials = self._get_credentials(request)
        if credentials:
            return credentials[0]

    def remember(self, request, principal, **kw):
        """ A no-op. Devpi authentication does not provide a protocol for
        remembering the user. Credentials are sent on every request.
        """
        return []

    def forget(self, request):
        """ Returns challenge headers. This should be attached to a response
        to indicate that credentials are required."""
        return [('WWW-Authenticate', 'Basic realm="%s"' % self.realm)]

    def callback(self, username, request):
        # Username arg is ignored.  Unfortunately _get_credentials winds up
        # getting called twice when authenticated_userid is called.  Avoiding
        # that, however, winds up duplicating logic from the superclass.
        credentials = self._get_credentials(request)
        if credentials:
            status, auth_user = self.auth.get_auth_status(credentials)
            request.log.debug("got auth status %r for user %r" % (status, auth_user))
            if status == "ok":
                return []
            elif status == "nouser":
                abort(request, 404, "user %r does not exist" % auth_user)
            elif status == "expired":
                abort_authenticate(request, msg="auth expired for %r" % auth_user)
            raise ValueError("Unknown authentication status: %s" % status)

    def _get_credentials(self, request):
        authorization = request.headers.get('X-Devpi-Auth')
        if not authorization:
            # support basic authentication for setup.py upload/register
            authorization = request.headers.get('Authorization')
            if not authorization:
                return None
            try:
                authmeth, auth = authorization.split(' ', 1)
            except ValueError: # not enough values to unpack
                return None
            if authmeth.lower() != 'basic':
                return None
        else:
            auth = authorization

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


