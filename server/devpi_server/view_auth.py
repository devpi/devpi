from pyramid.httpexceptions import HTTPFound
from devpi_common.types import cached_property
from devpi_common.types import ensure_unicode
from devpi_common.validation import normalize_name
from devpi_server.auth import Auth
from devpi_server.views import abort
from devpi_server.model import UpstreamError
from pyramid.authentication import CallbackAuthenticationPolicy
try:
    from pyramid.authorization import Allow, Deny, Everyone
except ImportError:
    from pyramid.security import Allow, Deny, Everyone


class RootFactory(object):
    def __init__(self, request):
        self.request = request
        xom = request.registry['xom']
        self.model = xom.model
        self.restrict_modify = xom.config.restrict_modify
        self.hook = xom.config.hook

    @cached_property
    def _user(self):
        if self.username:
            return self.model.get_user(self.username)

    @cached_property
    def _stage(self):
        if self.username and self.index:
            return self.model.getstage(self.username, self.index)

    @cached_property
    def matchdict(self):
        result = {}
        if not self.request.matchdict:
            return result
        for k, v in self.request.matchdict.items():
            if hasattr(v, 'rstrip'):
                v = v.rstrip('/')
            result[k] = v
        return result

    @cached_property
    def __acl__(self):
        acl = []
        if self.restrict_modify is None:
            acl.extend([
                (Allow, Everyone, 'user_create'),
                (Allow, 'root', 'user_modify'),
                (Allow, 'root', 'index_create')])
            if self.username:
                if self.username != 'root':
                    acl.extend([
                        (Allow, 'root', 'user_delete'),
                        (Allow, self.username, 'user_delete')])
                acl.extend([
                    (Allow, self.username, 'user_modify'),
                    (Allow, self.username, 'index_create')])
        else:
            for principal in self.restrict_modify:
                if self.username and self.username != principal:
                    acl.append((Allow, principal, 'user_delete'))
                acl.extend([
                    (Allow, principal, 'user_create'),
                    (Allow, principal, 'user_modify'),
                    (Allow, principal, 'index_create')])
        stage = self._stage
        if stage:
            acl.extend(stage.__acl__())
        acl = tuple(acl)
        all_denials = self.hook.devpiserver_auth_denials(
            request=self.request, acl=acl, user=self._user, stage=stage)
        if all_denials:
            denials = set().union(*all_denials)
            if denials:
                acl = tuple((Deny,) + denial for denial in denials) + acl
        return acl

    def getstage(self, user, index):
        stage = self.model.getstage(user, index)
        if not stage:
            abort(self.request, 404,
                  "The stage %s/%s could not be found." % (user, index))
        return stage

    def get_versiondata(self, project=None, version=None, perstage=False):
        if project is None:
            project = self.project
        if version is None:
            version = self.version
        if perstage:
            get = self.stage.get_versiondata_perstage
            msg = " on stage %r" %(self.index,)
        else:
            get = self.stage.get_versiondata
            msg = ""
        try:
            verdata = get(project, version)
        except UpstreamError as e:
            abort(self.request, 502, str(e))
        if not verdata:
            abort(self.request, 404,
                  "The version %s of project %s does not exist%s." %
                               (self.version, project, msg))
        return verdata

    def list_versions(self, project=None, perstage=False):
        if project is None:
            project = self.project
        try:
            if perstage:
                res = self.stage.list_versions_perstage(project)
            else:
                res = self.stage.list_versions(project)
        except UpstreamError as e:
            abort(self.request, 502, str(e))
        if not res and not self.stage.has_project(project):
            abort(self.request, 404, "no project %r" %(project))
        return res

    @cached_property
    def index(self):
        return self.matchdict.get('index')

    @cached_property
    def project(self):
        project = self.matchdict.get('project')
        if project is None:
            return

        # redirect GETs to non-normalized projects
        n_project = normalize_name(project)
        if n_project != project and self.request.method == 'GET':
            new_matchdict = dict(self.request.matchdict)
            new_matchdict['project'] = n_project
            route_name = self.request.matched_route.name
            url = self.request.route_url(route_name, **new_matchdict)
            raise HTTPFound(location=url)
        return n_project

    @cached_property
    def verified_project(self):
        name = self.project
        try:
            if not self.stage.has_project(name):
                abort(self.request, 404, "The project %s does not exist." %(name))
        except UpstreamError as e:
            abort(self.request, 502, str(e))
        return name

    @cached_property
    def version(self):
        version = self.matchdict.get('version')
        if version is None:
            return
        return ensure_unicode(version)

    @cached_property
    def stage(self):
        stage = self._stage
        if not stage:
            abort(
                self.request, 404, "The stage %s/%s could not be found." % (
                    self.username, self.index))
        return stage

    @cached_property
    def user(self):
        user = self._user
        if not user:
            abort(self.request, 404, "no user %r" % self.username)
        return user

    @cached_property
    def username(self):
        return self.matchdict.get('user')


class DevpiAuthenticationPolicy(CallbackAuthenticationPolicy):
    def __init__(self, xom):
        self.realm = "pypi"
        self.auth = Auth(xom.model, xom.config.get_auth_secret())
        self.hook = xom.config.hook

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
            status, auth_user, groups = self.auth.get_auth_status(
                credentials, request=request)
            request.log.debug("got auth status %r for user %r" % (status, auth_user))
            if status == "ok":
                return [":%s" % g for g in groups]
            return None

    def _get_credentials(self, request):
        return self.hook.devpiserver_get_credentials(request=request)

    def verify_credentials(self, request):
        credentials = self._get_credentials(request)
        if credentials:
            status = self.auth._get_auth_status(*credentials, request=request)
            if status.get("status") == "ok":
                return True
        return False
