from devpi_common.types import ensure_unicode
from devpi_server.auth import Auth
from devpi_server.views import abort, abort_authenticate, redirect
from devpi_server.model import UpstreamError
from pyramid.authentication import CallbackAuthenticationPolicy
from pyramid.decorator import reify
from pyramid.security import Allow, Deny, Everyone


class StageACL(object):
    def __init__(self, stage, restrict_modify):
        self.restrict_modify = restrict_modify
        self.stage = stage

    def __acl__(self):
        acl = []
        for principal in self.stage.ixconfig.get("acl_upload", []):
            if principal == ':ANONYMOUS:':
                principal = Everyone
            acl.append((Allow, principal, 'pypi_submit'))
        if self.restrict_modify is None:
            acl.extend([
                (Allow, self.stage.username, 'index_modify'),
                (Allow, self.stage.username, 'index_delete'),
                (Allow, self.stage.username, 'del_verdata'),
                (Allow, self.stage.username, 'del_project')])
        return acl


class RootFactory(object):
    def __init__(self, request):
        self.request = request
        xom = request.registry['xom']
        self.model = xom.model
        rm = xom.config.args.restrict_modify
        if rm is not None:
            rm = [x.strip() for x in rm.split(',')]
        self.restrict_modify = rm

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
        if self.restrict_modify is None:
            acl.extend([
                (Allow, Everyone, 'user_create'),
                (Allow, 'root', 'user_delete'),
                (Allow, 'root', 'user_modify'),
                (Allow, 'root', 'index_create'),
                (Allow, 'root', 'index_modify'),
                (Allow, 'root', 'index_delete'),
                (Allow, 'root', 'del_project'),
                (Allow, 'root', 'del_verdata')])
            if self.username == 'root':
                acl.append((Deny, Everyone, 'user_delete'))
            if self.username:
                acl.extend([
                    (Allow, self.username, 'user_delete'),
                    (Allow, self.username, 'user_modify'),
                    (Allow, self.username, 'index_create')])
        else:
            for principal in self.restrict_modify:
                acl.extend([
                    (Allow, principal, 'user_create'),
                    (Allow, principal, 'user_delete'),
                    (Allow, principal, 'user_modify'),
                    (Allow, principal, 'index_create'),
                    (Allow, principal, 'index_modify'),
                    (Allow, principal, 'index_delete'),
                    (Allow, principal, 'del_verdata'),
                    (Allow, principal, 'del_project')])
        stage = None
        if self.username and self.index:
            stage = self.model.getstage(self.username, self.index)
        if stage:
            stage.__acl__ = StageACL(stage, self.restrict_modify).__acl__
            acl.extend(stage.__acl__())
        return acl

    def getstage(self, user, index):
        stage = self.model.getstage(user, index)
        if not stage:
            abort(self.request, 404,
                  "The stage %s/%s could not be found." % (user, index))
        stage.__acl__ = StageACL(stage, self.restrict_modify).__acl__
        return stage

    def get_versiondata(self, projectname=None, version=None, perstage=False):
        if projectname is None:
            projectname = self.projectname  # raises 404 if not found
        if version is None:
            version = self.version
        if perstage:
            get = self.stage.get_versiondata_perstage
            msg = " on stage %r" %(self.index,)
        else:
            get = self.stage.get_versiondata
            msg = ""
        try:
            verdata = get(projectname, version)
        except UpstreamError as e:
            abort(self.request, 502, str(e))
        if not verdata:
            abort(self.request, 404,
                  "The version %s of project %s does not exist%s." %
                               (self.version, projectname, msg))
        return verdata

    def list_versions(self, projectname=None):
        if projectname is None:
            projectname = self.projectname
        try:
            return self.stage.list_versions(projectname)
        except UpstreamError as e:
            abort(self.request, 502, str(e))

    @reify
    def projectname(self):
        name = self.stage.get_projectname(self.name)
        if name is None:
            raise abort(self.request, 404,
                        "The project %s does not exist." % self.name)
        if self.request.method == 'GET' and name != self.name:
            new_matchdict = dict(self.request.matchdict)
            new_matchdict['name'] = name
            route_name = self.request.matched_route.name
            url = self.request.route_url(route_name, **new_matchdict)
            redirect(url)
        return name

    @reify
    def index(self):
        return self.matchdict.get('index')

    @reify
    def name(self):
        name = self.matchdict.get('name')
        if name is None:
            return
        return ensure_unicode(name)

    @reify
    def version(self):
        version = self.matchdict.get('version')
        if version is None:
            return
        return ensure_unicode(version)

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
        self.hook = xom.config.hook.devpiserver_auth_credentials

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
            status, auth_user, groups = self.auth.get_auth_status(credentials)
            request.log.debug("got auth status %r for user %r" % (status, auth_user))
            if status == "ok":
                return [":%s" % g for g in groups]
            elif status == "nouser":
                abort(request, 404, "user %r does not exist" % auth_user)
            elif status == "expired":
                abort_authenticate(request, msg="auth expired for %r" % auth_user)
            raise ValueError("Unknown authentication status: %s" % status)

    def _get_credentials(self, request):
        results = list(filter(None, self.hook(request=request)))
        if results:
            return results[0]
