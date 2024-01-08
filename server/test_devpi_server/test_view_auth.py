from devpi_server.config import hookimpl
import pytest


@pytest.fixture
def dsp(xom):
    from devpi_server.view_auth import DevpiSecurityPolicy
    return DevpiSecurityPolicy(xom)


class TestCredentialPlugin:
    @pytest.fixture
    def plugin(self):
        class Plugin:
            @hookimpl
            def devpiserver_get_credentials(self, request):
                return self.results.pop()
        return Plugin()

    @pytest.fixture
    def xom(self, makexom, plugin):
        xom = makexom(plugins=[plugin])
        return xom

    def test_credential_plugin_no_credentials(self, blank_request, dsp, plugin):
        plugin.results = [None]
        request = blank_request()
        assert dsp._get_credentials(request) is None

    def test_credential_plugin_got_credentials(self, blank_request, dsp, plugin):
        plugin.results = [('foo', 'bar')]
        request = blank_request()
        assert dsp._get_credentials(request) == ('foo', 'bar')


class TestCredentialPlugins:
    @pytest.fixture
    def plugin1(self):
        class Plugin:
            @hookimpl
            def devpiserver_get_credentials(self, request):
                return self.results.pop()
        return Plugin()

    @pytest.fixture
    def plugin2(self):
        class Plugin:
            @hookimpl
            def devpiserver_get_credentials(self, request):
                return self.results.pop()
        return Plugin()

    @pytest.fixture
    def xom(self, makexom, plugin1, plugin2):
        import random
        plugins = [plugin1, plugin2]
        random.shuffle(plugins)
        xom = makexom(plugins=plugins)
        return xom

    def test_credential_plugins_no_credentials(self, blank_request, dsp, plugin1, plugin2):
        plugin1.results = [None]
        plugin2.results = [None]
        request = blank_request()
        assert dsp._get_credentials(request) is None

    def test_credential_plugins_got_one_credential(self, blank_request, dsp, plugin1, plugin2):
        plugin1.results = [('foo', 'bar')]
        plugin2.results = [None]
        request = blank_request()
        assert dsp._get_credentials(request) == ('foo', 'bar')

    def test_credential_plugins_got_another_credential(self, blank_request, dsp, plugin1, plugin2):
        plugin1.results = [None]
        plugin2.results = [('foo', 'bar')]
        request = blank_request()
        assert dsp._get_credentials(request) == ('foo', 'bar')

    def test_credential_plugins_got_two_credential(self, blank_request, dsp, plugin1, plugin2):
        plugin1.results = [('ham', 'egg')]
        plugin2.results = [('foo', 'bar')]
        request = blank_request()
        # one of them wins, depends on entry point order and is undefined
        assert dsp._get_credentials(request) in [('ham', 'egg'), ('foo', 'bar')]


class TestHeaderCredentialPlugin:
    @pytest.fixture
    def plugin(self):
        class Plugin:
            @hookimpl
            def devpiserver_get_credentials(self, request):
                if 'X-Devpi-User' in request.headers:
                    return (request.headers['X-Devpi-User'], '')
        return Plugin()

    @pytest.fixture
    def xom(self, makexom, plugin):
        return makexom(plugins=[plugin])

    def test_credential_plugin_no_credentials(self, blank_request, dsp, plugin):
        request = blank_request()
        assert dsp._get_credentials(request) is None

    def test_credential_plugin_got_credentials(self, blank_request, dsp, plugin):
        request = blank_request()
        request.headers['X-Devpi-User'] = 'foo'
        assert dsp._get_credentials(request) == ('foo', '')


class TestDevpiSecurityPolicy:
    @pytest.fixture
    def policy(self, xom):
        from devpi_server.view_auth import DevpiSecurityPolicy
        return DevpiSecurityPolicy(xom)

    @pytest.fixture
    def blank_request(self, blank_request, policy, pyramidconfig, xom):
        from pyramid.interfaces import ISecurityPolicy
        from pyramid.threadlocal import get_current_registry
        request = blank_request()
        request.registry = get_current_registry()
        request.registry.registerUtility(policy, ISecurityPolicy)
        request.log = xom.log
        request.route_url = lambda x: x
        return request

    def test_nouser_basic(self, blank_request, policy, xom):
        from pyramid.authentication import b64encode
        blank_request.headers['Authorization'] = 'BASIC ' + b64encode('foo:bar').decode("ascii")
        assert policy.identity(blank_request) is None

    def test_expired(self, blank_request, mock, policy, xom):
        from pyramid.authentication import b64encode
        with mock.patch('time.time') as timemock:
            timemock.return_code = 0.0
            passwd = policy.auth.serializer.dumps(('foo', []))
        blank_request.headers['X-Devpi-Auth'] = b64encode('foo:%s' % passwd).decode("ascii")
        assert policy.identity(blank_request) is None
