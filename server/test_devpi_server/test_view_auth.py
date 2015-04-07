import pytest


@pytest.fixture
def dap(xom):
    from devpi_server.view_auth import DevpiAuthenticationPolicy
    return DevpiAuthenticationPolicy(xom)


class TestCredentialPlugin:
    @pytest.fixture
    def plugin(self):
        class Plugin:
            def devpiserver_auth_credentials(self, request):
                return self.results.pop()
        return Plugin()

    @pytest.fixture
    def xom(self, makexom, plugin):
        xom = makexom(plugins=[(plugin, None)])
        return xom

    def test_credential_plugin_no_credentials(self, blank_request, dap, plugin):
        plugin.results = [None]
        request = blank_request()
        assert dap._get_credentials(request) is None

    def test_credential_plugin_got_credentials(self, blank_request, dap, plugin):
        plugin.results = [('foo', 'bar')]
        request = blank_request()
        assert dap._get_credentials(request) == ('foo', 'bar')


class TestCredentialPlugins:
    @pytest.fixture
    def plugin1(self):
        class Plugin:
            def devpiserver_auth_credentials(self, request):
                return self.results.pop()
        return Plugin()

    @pytest.fixture
    def plugin2(self):
        class Plugin:
            def devpiserver_auth_credentials(self, request):
                return self.results.pop()
        return Plugin()

    @pytest.fixture
    def xom(self, makexom, plugin1, plugin2):
        import random
        plugins = [(plugin1, None), (plugin2, None)]
        random.shuffle(plugins)
        xom = makexom(plugins=plugins)
        return xom

    def test_credential_plugins_no_credentials(self, blank_request, dap, plugin1, plugin2):
        plugin1.results = [None]
        plugin2.results = [None]
        request = blank_request()
        assert dap._get_credentials(request) is None

    def test_credential_plugins_got_one_credential(self, blank_request, dap, plugin1, plugin2):
        plugin1.results = [('foo', 'bar')]
        plugin2.results = [None]
        request = blank_request()
        assert dap._get_credentials(request) == ('foo', 'bar')

    def test_credential_plugins_got_another_credential(self, blank_request, dap, plugin1, plugin2):
        plugin1.results = [None]
        plugin2.results = [('foo', 'bar')]
        request = blank_request()
        assert dap._get_credentials(request) == ('foo', 'bar')

    def test_credential_plugins_got_two_credential(self, blank_request, dap, plugin1, plugin2):
        plugin1.results = [('ham', 'egg')]
        plugin2.results = [('foo', 'bar')]
        request = blank_request()
        # one of them wins, depends on entry point order and is undefined
        assert dap._get_credentials(request) in [('ham', 'egg'), ('foo', 'bar')]


class TestHeaderCredentialPlugin:
    @pytest.fixture
    def plugin(self):
        class Plugin:
            def devpiserver_auth_credentials(self, request):
                if 'X-Devpi-User' in request.headers:
                    return (request.headers['X-Devpi-User'], '')
        return Plugin()

    @pytest.fixture
    def xom(self, makexom, plugin):
        xom = makexom(plugins=[(plugin, None)])
        return xom

    def test_credential_plugin_no_credentials(self, blank_request, dap, plugin):
        request = blank_request()
        assert dap._get_credentials(request) is None

    def test_credential_plugin_got_credentials(self, blank_request, dap, plugin):
        request = blank_request()
        request.headers['X-Devpi-User'] = 'foo'
        assert dap._get_credentials(request) == ('foo', '')
