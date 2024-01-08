from devpi_server.config import hookimpl
import pytest

pytestmark = [pytest.mark.writetransaction]


@pytest.fixture
def stage(request, model):
    config = {"index": "world", "bases": (),
              "type": "stage", "volatile": True}
    if "bases" in request.fixturenames:
        config["bases"] = request.getfixturevalue("bases")
    user = model.create_user("hello", password="123")
    return user.create_stage(**config)


@pytest.fixture
def permissionrequest(model):
    from devpi_server.view_auth import DevpiSecurityPolicy
    from pyramid.interfaces import ISecurityPolicy
    from pyramid.request import Request
    from pyramid.threadlocal import get_current_registry
    policy = DevpiSecurityPolicy(model.xom)
    dummyrequest = Request.blank('/')
    dummyrequest.registry = get_current_registry()
    dummyrequest.registry.registerUtility(policy, ISecurityPolicy)
    dummyrequest.registry['xom'] = model.xom
    dummyrequest.log = model.xom.log
    return dummyrequest


@pytest.fixture
def plugin():
    class Plugin:
        @hookimpl
        def devpiserver_auth_request(self, request, userdict, username, password):
            if username == 'external':
                return dict(
                    status='ok',
                    groups=['developer'])
            return None
    return Plugin()


@pytest.fixture
def xom(makexom, plugin):
    return makexom(plugins=[plugin])


def with_user(request, user):
    from pyramid.authentication import b64encode
    from pyramid.security import ISecurityPolicy
    if user is None:
        request.headers.pop('Authorization', None)
    else:
        if user == 'root':
            auth = "root:"
        else:
            auth = "%s:123" % user
        request.headers['Authorization'] = 'Basic %s' % b64encode(
            auth.encode('utf-8')).decode('ascii')
    policy = request.registry.queryUtility(ISecurityPolicy)
    policy.identity_cache.clear(request)
    return request


class TestStage:
    # test both pypi_submit and upload for BBB
    @pytest.mark.parametrize("permission", ('pypi_submit', 'upload'))
    def test_set_and_get_acl_upload(self, xom, model, plugin, stage, permission, permissionrequest):
        indexconfig = stage.ixconfig
        # check that "hello" was included in acl_upload by default
        assert indexconfig["acl_upload"] == ["hello"]
        stage = model.getstage("hello/world")
        # root cannot upload
        assert not with_user(permissionrequest, 'root').has_permission(permission, stage)
        # but hello can upload
        assert with_user(permissionrequest, 'hello').has_permission(permission, stage)
        # anonymous can't
        assert not with_user(permissionrequest, None).has_permission(permission, stage)
        # external can't
        assert not with_user(permissionrequest, 'external').has_permission(permission, stage)

        # and we remove 'hello' from acl_upload ...
        stage.modify(acl_upload=[])
        # ... now it cannot upload either
        assert not with_user(permissionrequest, 'hello').has_permission(permission, stage)

        # and we set the special :ANONYMOUS: for acl_upload ...
        stage.modify(acl_upload=[':anonymous:'])
        # which is always changed to uppercase
        assert stage.ixconfig['acl_upload'] == [':ANONYMOUS:']
        # and now anyone can upload
        assert with_user(permissionrequest, 'hello').has_permission(permission, stage)
        assert with_user(permissionrequest, 'root').has_permission(permission, stage)
        assert with_user(permissionrequest, None).has_permission(permission, stage)

        # and we set the group :developer for acl_upload ...
        stage.modify(acl_upload=[':developer'])
        # no one ...
        assert not with_user(permissionrequest, 'hello').has_permission(permission, stage)
        assert not with_user(permissionrequest, 'root').has_permission(permission, stage)
        assert not with_user(permissionrequest, None).has_permission(permission, stage)
        # except external can upload
        assert with_user(permissionrequest, 'external').has_permission(permission, stage)

    def test_set_and_get_acl_toxresult_upload(self, xom, model, plugin, stage, permissionrequest):
        indexconfig = stage.ixconfig
        # check that "hello" was included in acl_upload by default
        assert indexconfig["acl_toxresult_upload"] == [":ANONYMOUS:"]

        stage = model.getstage("hello/world")

        # anonymous may upload tests
        assert with_user(permissionrequest, None).has_permission(
            'toxresult_upload', stage)

        stage.modify(acl_toxresult_upload=['hello'])
        # hello may upload
        assert with_user(permissionrequest, 'hello').has_permission(
            'toxresult_upload', stage)
        # but anonymous may not
        assert not with_user(permissionrequest, None).has_permission(
            'toxresult_upload', stage)
        # neither may external
        assert not with_user(permissionrequest, 'external').has_permission(
            'toxresult_upload', stage)

        # and we remove 'hello' from acl_upload ...
        stage.modify(acl_toxresult_upload=[])
        # ... now he may not upload either
        assert not with_user(permissionrequest, 'hello').has_permission(
            'toxresult_upload', stage)

        # and we set the group :developer for acl_upload ...
        stage.modify(acl_toxresult_upload=[':developer'])
        # no one ...
        assert not with_user(permissionrequest, 'hello').has_permission(
            'toxresult_upload', stage)
        assert not with_user(permissionrequest, 'root').has_permission(
            'toxresult_upload', stage)
        assert not with_user(permissionrequest, None).has_permission(
            'toxresult_upload', stage)
        # except external can upload
        assert with_user(permissionrequest, 'external').has_permission(
            'toxresult_upload', stage)


class TestAuthDenialPlugin:
    @pytest.fixture
    def plugin(self):
        class Plugin:
            @hookimpl
            def devpiserver_auth_denials(self, request, acl, user, stage):
                return self.results.pop()
        return Plugin()

    @pytest.fixture
    def xom(self, makexom, plugin):
        xom = makexom(plugins=[plugin])
        return xom

    def test_denials_plugin(self, permissionrequest, plugin, xom):
        from devpi_server.view_auth import RootFactory
        request = with_user(permissionrequest, 'root')
        request.registry['xom'] = xom
        context = RootFactory(request)
        plugin.results = [None]
        assert request.has_permission('user_create', context)
        context = RootFactory(request)
        plugin.results = [[('root', 'user_create')]]
        assert not request.has_permission('user_create', context)

    @pytest.mark.notransaction
    def test_deny_login(self, plugin, xom, mapp):
        plugin.results = [None]
        mapp.login("root", "")
        assert plugin.results == []
        mapp.logout()
        plugin.results = [[('root', 'user_login')]]
        mapp.login("root", "", code=401)
        assert plugin.results == []

    def test_deny_acl_upload_push(self, makexom, makemapp, maketestapp):
        from pyramid.authorization import Everyone
        from pyramid.util import is_nonstr_iter
        import json

        class Plugin:
            allowed = None
            called = 0

            @hookimpl
            def devpiserver_auth_denials(self, request, acl, user, stage):
                if self.allowed is None:
                    return None
                identity = request.identity
                if identity is None:
                    return None
                self.called += 1
                denials = set()
                allowed = self.allowed
                for ace_action, ace_principal, ace_permissions in acl:
                    if not is_nonstr_iter(ace_permissions):
                        ace_permissions = [ace_permissions]
                    for ace_permission in ace_permissions:
                        if ace_permission in denials:
                            continue
                        deny = (
                            ace_permission.startswith("user_")
                            or (allowed is not None and ace_permission not in allowed))
                        if deny:
                            denials.add(ace_permission)
                return {(Everyone, x) for x in denials}

        plugin = Plugin()
        xom = makexom(plugins=[plugin])
        testapp = maketestapp(xom)
        mapp = makemapp(testapp)
        api1 = mapp.create_and_use()
        mapp.upload_file_pypi("hello-1.0.tar.gz", b"content", "hello", "1.0")
        api2 = mapp.create_index('dev2')
        plugin.allowed = frozenset(('pkg_read', 'toxresult_upload'))
        plugin.called = 0
        req = dict(name="hello", version="1.0", targetindex=api2.stagename)
        r = testapp.push(api1.index, json.dumps(req))
        assert plugin.called
        assert r.status_code == 401
        assert mapp.getreleaseslist(
            'hello', indexname=api2.stagename, code=404) is None
        plugin.allowed = frozenset(('pkg_read', 'toxresult_upload', 'upload'))
        plugin.called = 0
        req = dict(name="hello", version="1.0", targetindex=api2.stagename)
        r = testapp.push(api1.index, json.dumps(req))
        assert plugin.called
        assert r.status_code == 200
        assert mapp.getreleaseslist('hello', indexname=api2.stagename) == [
            f"{api2.index}/+f/ed7/002b439e9ac84/hello-1.0.tar.gz"]
