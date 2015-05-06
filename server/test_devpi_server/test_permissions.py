from __future__ import unicode_literals
import pytest

pytestmark = [pytest.mark.writetransaction]


@pytest.fixture
def stage(request, model):
    config = {"index": "world", "bases": (),
              "type": "stage", "volatile": True}
    if "bases" in request.fixturenames:
        config["bases"] = request.getfuncargvalue("bases")
    user = model.create_user("hello", password="123")
    return user.create_stage(**config)


@pytest.fixture
def permissionrequest(dummyrequest, model):
    from devpi_server.view_auth import DevpiAuthenticationPolicy
    from pyramid.authorization import ACLAuthorizationPolicy
    from pyramid.interfaces import IAuthenticationPolicy
    from pyramid.interfaces import IAuthorizationPolicy
    policy = DevpiAuthenticationPolicy(model.xom)
    dummyrequest.registry.registerUtility(policy, IAuthenticationPolicy)
    policy = ACLAuthorizationPolicy()
    dummyrequest.registry.registerUtility(policy, IAuthorizationPolicy)
    dummyrequest.log = model.xom.log
    return dummyrequest


@pytest.fixture
def plugin():
    class Plugin:
        def devpiserver_auth_user(self, userdict, username, password):
            if username == 'external':
                return dict(
                    status='ok',
                    groups=['developer'])
            return dict(status="unknown")
    return Plugin()


@pytest.fixture
def xom(makexom, plugin):
    return makexom(plugins=[plugin])


def with_user(request, user):
    from pyramid.authentication import b64encode
    if user is None:
        request.headers.pop('Authorization', None)
    else:
        if user == 'root':
            auth = "root:"
        else:
            auth = "%s:123" % user
        request.headers['Authorization'] = 'Basic %s' % b64encode(
            auth.encode('utf-8')).decode('ascii')
    return request


class TestStage:
    def test_set_and_get_acl(self, xom, model, plugin, stage, permissionrequest):
        from devpi_server.view_auth import StageACL
        indexconfig = stage.ixconfig
        # check that "hello" was included in acl_upload by default
        assert indexconfig["acl_upload"] == ["hello"]
        stage = model.getstage("hello/world")
        # root cannot upload
        assert not with_user(permissionrequest, 'root').has_permission('pypi_submit', StageACL(stage, False))
        # but hello can upload
        assert with_user(permissionrequest, 'hello').has_permission('pypi_submit', StageACL(stage, False))
        # anonymous can't
        assert not with_user(permissionrequest, None).has_permission('pypi_submit', StageACL(stage, False))
        # external can't
        assert not with_user(permissionrequest, 'external').has_permission('pypi_submit', StageACL(stage, False))

        # and we remove 'hello' from acl_upload ...
        stage.modify(acl_upload=[])
        # ... now it cannot upload either
        stage = model.getstage("hello/world")
        assert not with_user(permissionrequest, 'hello').has_permission('pypi_submit', StageACL(stage, False))

        # and we set the special :ANONYMOUS: for acl_upload ...
        stage.modify(acl_upload=[':anonymous:'])
        # which is always changed to uppercase
        assert stage.ixconfig['acl_upload'] == [':ANONYMOUS:']
        # and now anyone can upload
        stage = model.getstage("hello/world")
        assert with_user(permissionrequest, 'hello').has_permission('pypi_submit', StageACL(stage, False))
        assert with_user(permissionrequest, 'root').has_permission('pypi_submit', StageACL(stage, False))
        assert with_user(permissionrequest, None).has_permission('pypi_submit', StageACL(stage, False))

        # and we set the group :developer for acl_upload ...
        stage.modify(acl_upload=[':developer'])
        # no one ...
        assert not with_user(permissionrequest, 'hello').has_permission('pypi_submit', StageACL(stage, False))
        assert not with_user(permissionrequest, 'root').has_permission('pypi_submit', StageACL(stage, False))
        assert not with_user(permissionrequest, None).has_permission('pypi_submit', StageACL(stage, False))
        # except external can upload
        assert with_user(permissionrequest, 'external').has_permission('pypi_submit', StageACL(stage, False))
