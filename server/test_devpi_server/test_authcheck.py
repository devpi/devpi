from devpi_server.config import hookimpl
from webob.headers import ResponseHeaders
import pytest


pytestmark = [pytest.mark.notransaction]


class Plugin:
    @hookimpl
    def devpiserver_authcheck_unauthorized(self, request):
        if not request.authenticated_userid:
            return True


def test_authcheck_basic_auth(makemapp, maketestapp, makexom):
    from pyramid.authentication import b64encode
    xom = makexom(plugins=[Plugin()])
    testapp = maketestapp(xom)
    mapp = makemapp(testapp)
    mapp.create_user("user1", "1")
    testapp.xget(
        401, 'http://localhost/+authcheck',
        headers=ResponseHeaders({
            'X-Original-URI': 'http://localhost/'}))
    basic_auth = '%s:%s' % ('user1', '1')
    testapp.xget(
        200, 'http://localhost/+authcheck',
        headers=ResponseHeaders({
            'Authorization': 'Basic %s' % b64encode(basic_auth).decode('ascii'),
            'X-Original-URI': 'http://localhost/'}))


def test_authcheck_devpi_auth(makemapp, maketestapp, makexom):
    xom = makexom(plugins=[Plugin()])
    testapp = maketestapp(xom)
    mapp = makemapp(testapp)
    mapp.create_user("user1", "1")
    testapp.xget(
        401, 'http://localhost/+authcheck',
        headers=ResponseHeaders({
            'X-Original-URI': 'http://localhost/'}))
    testapp.set_auth('user1', '1')
    testapp.xget(
        200, 'http://localhost/+authcheck',
        headers=ResponseHeaders({
            'X-Original-URI': 'http://localhost/'}))


def test_authcheck_always_ok(testapp):
    testapp.xget(
        200, 'http://localhost/+authcheck',
        headers=ResponseHeaders({
            'X-Original-URI': 'http://localhost/+api'}))
    testapp.xget(
        200, 'http://localhost/+authcheck',
        headers=ResponseHeaders({
            'X-Original-URI': 'http://localhost/+login'}))
