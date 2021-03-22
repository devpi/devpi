import itsdangerous
import pytest
from devpi_server.auth import getpwhash
from devpi_server.auth import hash_password
from devpi_server.auth import newsalt
from devpi_server.auth import verify_and_update_password_hash
from devpi_server.config import hookimpl

pytestmark = [pytest.mark.writetransaction]


class TestAuth:
    @pytest.fixture
    def auth(self, model):
        from devpi_server.views import Auth
        return Auth(model, "qweqwe")

    def test_auth_direct(self, model, auth):
        model.create_user("user", password="world")
        result = auth._get_auth_status("user", "world")
        assert result == dict(status="ok", from_user_object=True)

    def test_proxy_auth(self, model, auth):
        model.create_user("user", password="world")
        assert auth.new_proxy_auth("user", "wrongpass") is None
        assert auth.new_proxy_auth("uer", "wrongpass") is None
        res = auth.new_proxy_auth("user", "world")
        assert "password" in res and "expiration" in res
        assert auth._get_auth_status("user", res["password"]) == dict(status="ok", groups=[])

    def test_proxy_auth_expired(self, model, auth, monkeypatch):
        username, password = "user", "world"

        model.create_user(username, password=password)
        proxy = auth.new_proxy_auth(username, password)

        def r(*args, **kw):
            raise itsdangerous.SignatureExpired("123")

        monkeypatch.setattr(auth.serializer, "loads", r)

        assert auth._get_auth_status(username, proxy["password"]) == dict(status="expired")

    def test_auth_status_no_user(self, auth):
        assert auth._get_auth_status("user1", "123") == dict(status="nouser")

    def test_auth_status_proxy_user(self, model, auth):
        username, password = "user", "world"
        model.create_user(username, password)
        proxy = auth.new_proxy_auth(username, password)
        result = auth._get_auth_status(username, proxy["password"])
        assert result == dict(status="ok", groups=[])

    def test_auth_status_cached(self, auth, model, monkeypatch):
        from devpi_server.model import User
        username, password = "user", "world"
        model.create_user(username, password)
        orig_validate = User.validate

        def validate(self, authpassword):
            result = orig_validate(self, authpassword)
            # block original to error on second use
            User.validate = lambda s, a: 0 / 0
            return result

        monkeypatch.setattr(User, "validate", validate)
        assert auth._validate(username, password) == dict(
            status="ok",
            from_user_object=True)
        # with no request there is no caching, so the second call errors
        with pytest.raises(ZeroDivisionError):
            assert auth._validate(username, password) == dict(
                status="ok",
                from_user_object=True)

        # patch again and use a fake request
        class Request:
            pass

        request = Request()
        monkeypatch.setattr(User, "validate", validate)
        assert auth._validate(username, password, request=request) == dict(
            status="ok",
            from_user_object=True)
        assert getattr(request, '__devpiserver_user_validate_result') is True
        assert auth._validate(username, password, request=request) == dict(
            status="ok",
            from_user_object=True)


def test_newsalt():
    assert newsalt() != newsalt()


def test_hash_verification():
    hash = hash_password("hello")
    assert verify_and_update_password_hash("hello", hash) == (True, None)
    assert verify_and_update_password_hash("xy", hash) == (False, None)


def test_hash_migration():
    secret = "hello"
    salt = newsalt()
    hash = getpwhash(secret, salt)
    (valid, newhash) = verify_and_update_password_hash(secret, hash, salt=salt)
    assert valid
    assert newhash != hash
    assert newhash.startswith('$argon2')


class TestAuthPlugin:
    @pytest.fixture
    def plugin(self):
        class Plugin:
            @hookimpl
            def devpiserver_auth_request(self, request, userdict, username, password):
                return self.results.pop()
        return Plugin()

    @pytest.fixture
    def xom(self, makexom, plugin):
        xom = makexom(plugins=[plugin])
        return xom

    @pytest.fixture
    def auth(self, model):
        from devpi_server.views import Auth
        return Auth(model, "qweqwe")

    def test_auth_plugin_no_user(self, auth, plugin):
        plugin.results = [None]
        username, password = "user", "world"
        assert auth._get_auth_status(username, password) == dict(status='nouser')
        assert plugin.results == []  # all results used

    def test_auth_plugin_no_user_pass_through(self, auth, model, plugin):
        plugin.results = [None]
        username, password = "user", "world"
        model.create_user(username, password)
        assert auth._get_auth_status(username, password) == dict(
            status='ok', from_user_object=True)
        assert plugin.results == []  # all results used

    def test_auth_plugin_invalid_credentials(self, auth, model, plugin):
        plugin.results = [dict(status="reject")]
        username, password = "user", "world"
        model.create_user(username, password)
        assert auth._get_auth_status(username, password) == dict(status='reject')
        assert plugin.results == []  # all results used

    def test_auth_plugin_root_internal(self, auth, plugin):
        plugin.results = [dict(status="reject")]
        assert auth._get_auth_status("root", "") == dict(
            status='ok', from_user_object=True)
        # the plugin should not have been called
        assert plugin.results == [dict(status="reject")]

    def test_auth_plugin_groups(self, auth, plugin):
        plugin.results = [dict(status="ok", groups=['group'])]
        username, password = "user", "world"
        assert auth._get_auth_status(username, password) == dict(status='ok', groups=['group'])
        assert plugin.results == []  # all results used

    def test_auth_plugin_no_groups(self, auth, plugin):
        plugin.results = [dict(status="ok")]
        username, password = "user", "world"
        assert auth._get_auth_status(username, password) == dict(status='ok')
        assert plugin.results == []  # all results used

    def test_auth_plugin_invalid_status(self, auth, plugin):
        plugin.results = [dict(status="siotheiasoehn")]
        username, password = "user", "world"
        assert auth._get_auth_status(username, password) == dict(status='reject')
        assert plugin.results == []  # all results used


class TestAuthPlugins:
    @pytest.fixture
    def plugin1(self):
        class Plugin:
            @hookimpl
            def devpiserver_auth_user(self, userdict, username, password):
                return self.results.pop()
        return Plugin()

    @pytest.fixture
    def plugin2(self):
        class Plugin:
            @hookimpl
            def devpiserver_auth_user(self, userdict, username, password):
                return self.results.pop()
        return Plugin()

    @pytest.fixture
    def xom(self, makexom, plugin1, plugin2):
        xom = makexom(plugins=[plugin1,plugin2])
        return xom

    @pytest.fixture
    def auth(self, model):
        from devpi_server.views import Auth
        return Auth(model, "qweqwe")

    def test_auth_plugins_groups_combined(self, auth, plugin1, plugin2):
        plugin1.results = [dict(status="ok", groups=['group1', 'common'])]
        plugin2.results = [dict(status="ok", groups=['group2', 'common'])]
        username, password = "user", "world"
        assert auth._get_auth_status(username, password) == dict(
            status='ok', groups=['common', 'group1', 'group2'])
        assert plugin1.results == []  # all results used
        assert plugin2.results == []  # all results used

    def test_auth_plugins_invalid_credentials(self, auth, plugin1, plugin2):
        plugin1.results = [dict(status="ok", groups=['group1', 'common'])]
        plugin2.results = [dict(status="reject")]
        username, password = "user", "world"
        # one failed authentication in any plugin is enough to stop
        assert auth._get_auth_status(username, password) == dict(status='reject')
        assert plugin1.results == []  # all results used
        assert plugin2.results == []  # all results used
        plugin1.results = [dict(status="reject")]
        plugin2.results = [dict(status="ok", groups=['group1', 'common'])]
        # one failed authentication in any plugin is enough to stop
        assert auth._get_auth_status(username, password) == dict(status='reject')
        assert plugin1.results == []  # all results used
        assert plugin2.results == []  # all results used

    def test_auth_plugins_passthrough(self, auth, plugin1, plugin2):
        plugin1.results = [None]
        plugin2.results = [dict(status="ok", groups=['group2', 'common'])]
        username, password = "user", "world"
        assert auth._get_auth_status(username, password) == dict(
            status='ok', groups=['common', 'group2'])
        assert plugin1.results == []  # all results used
        assert plugin2.results == []  # all results used
