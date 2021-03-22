from pyramid.httpexceptions import HTTPFound
from devpi_common.types import cached_property
from devpi_common.types import ensure_unicode
from devpi_common.validation import normalize_name
from devpi_server.auth import Auth
from devpi_server.config import hookimpl
from devpi_server.views import abort
from devpi_server.model import UpstreamError
from pyramid.authorization import ACLHelper, Allow, Authenticated, Deny, Everyone
from pyramid.interfaces import ISecurityPolicy
from pyramid.request import RequestLocalCache


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
        acl = [(Allow, Everyone, 'user_login')]
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


class CredentialsIdentity:
    def __init__(self, username, groups):
        self.username = username
        self.groups = groups


class DevpiSecurityPolicy:
    def __init__(self, xom):
        self.realm = "pypi"
        self.auth = Auth(xom.model, xom.config.get_auth_secret())
        self.hook = xom.config.hook
        self.identity_cache = RequestLocalCache(self.load_identity)

    def remember(self, request, userid, **kw):
        # A no-op. Devpi authentication does not provide a protocol for
        # remembering the user. Credentials are sent on every request.
        return []

    def forget(self, request, **kw):
        return [('WWW-Authenticate', 'Basic realm="%s"' % self.realm)]

    def _get_credentials(self, request):
        return self.hook.devpiserver_get_credentials(request=request)

    def load_identity(self, request):
        credentials = self._get_credentials(request)
        return self.hook.devpiserver_get_identity(
            request=request, credentials=credentials)

    def identity(self, request):
        return self.identity_cache.get_or_create(request)

    def authenticated_userid(self, request):
        # defer to the identity logic to determine if the user id logged in
        # and return None if they are not
        identity = request.identity
        if identity is not None:
            return identity.username

    def permits(self, request, context, permission):
        # use the identity to build a list of principals, and pass them
        # to the ACLHelper to determine allowed/denied
        identity = request.identity
        principals = set([Everyone])
        if identity is not None:
            principals.add(Authenticated)
            principals.add(identity.username)
            principals.update(":" + g for g in identity.groups)
        return ACLHelper().permits(context, principals, permission)


@hookimpl(trylast=True)
def devpiserver_get_identity(request, credentials):
    if credentials is None:
        return
    policy = request.registry.getUtility(ISecurityPolicy)
    result = policy.auth._get_auth_status(*credentials, request=request)
    status = result["status"]
    if status != "ok":
        return
    return CredentialsIdentity(
        credentials[0], result.get("groups", []))
