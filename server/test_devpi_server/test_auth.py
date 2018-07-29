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
        assert auth._get_auth_status("user", "world") == dict(status="ok")

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

        def r(*args, **kw): raise itsdangerous.SignatureExpired("123")
        monkeypatch.setattr(auth.serializer, "loads", r)

        assert auth._get_auth_status(username, proxy["password"]) == dict(status="expired")
        assert auth.get_auth_status((username, proxy["password"])) == ["expired", username, []]

    def test_auth_status_no_auth(self, auth):
        assert auth.get_auth_status(None) == ["noauth", "", []]

    def test_auth_status_no_user(self, auth):
        assert auth.get_auth_status(("user1", "123")) == ["nouser", "user1", []]

    def test_auth_status_proxy_user(self, model, auth):
        username, password = "user", "world"
        model.create_user(username, password)
        proxy = auth.new_proxy_auth(username, password)
        assert auth.get_auth_status((username, proxy["password"])) == \
               ["ok", username, []]

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
            def devpiserver_auth_user(self, userdict, username, password):
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
        plugin.results = [dict(status="unknown")]
        username, password = "user", "world"
        assert auth.get_auth_status((username, password)) == ['nouser', 'user', []]
        assert plugin.results == []  # all results used

    def test_auth_plugin_no_user_pass_through(self, auth, model, plugin):
        plugin.results = [dict(status="unknown")]
        username, password = "user", "world"
        model.create_user(username, password)
        assert auth.get_auth_status((username, password)) == ['ok', username, []]
        assert plugin.results == []  # all results used

    def test_auth_plugin_invalid_credentials(self, auth, model, plugin):
        plugin.results = [dict(status="reject")]
        username, password = "user", "world"
        model.create_user(username, password)
        assert auth.get_auth_status((username, password)) == ['nouser', username, []]
        assert plugin.results == []  # all results used

    def test_auth_plugin_root_internal(self, auth, plugin):
        plugin.results = [dict(status="reject")]
        assert auth.get_auth_status(("root", "")) == ['ok', 'root', []]
        # the plugin should not have been called
        assert plugin.results == [dict(status="reject")]

    def test_auth_plugin_groups(self, auth, plugin):
        plugin.results = [dict(status="ok", groups=['group'])]
        username, password = "user", "world"
        assert auth.get_auth_status((username, password)) == ['ok', username, ['group']]
        assert plugin.results == []  # all results used

    def test_auth_plugin_no_groups(self, auth, plugin):
        plugin.results = [dict(status="ok")]
        username, password = "user", "world"
        assert auth.get_auth_status((username, password)) == ['ok', username, []]
        assert plugin.results == []  # all results used

    def test_auth_plugin_invalid_status(self, auth, plugin):
        plugin.results = [dict(status="siotheiasoehn")]
        username, password = "user", "world"
        assert auth.get_auth_status((username, password)) == ['nouser', username, []]
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
        assert auth.get_auth_status((username, password)) == [
            'ok', username, ['common', 'group1', 'group2']]
        assert plugin1.results == []  # all results used
        assert plugin2.results == []  # all results used

    def test_auth_plugins_invalid_credentials(self, auth, plugin1, plugin2):
        plugin1.results = [dict(status="ok", groups=['group1', 'common'])]
        plugin2.results = [dict(status="reject")]
        username, password = "user", "world"
        # one failed authentication in any plugin is enough to stop
        assert auth.get_auth_status((username, password)) == ['nouser', username, []]
        assert plugin1.results == []  # all results used
        assert plugin2.results == []  # all results used
        plugin1.results = [dict(status="reject")]
        plugin2.results = [dict(status="ok", groups=['group1', 'common'])]
        # one failed authentication in any plugin is enough to stop
        assert auth.get_auth_status((username, password)) == ['nouser', username, []]
        assert plugin1.results == []  # all results used
        assert plugin2.results == []  # all results used

    def test_auth_plugins_passthrough(self, auth, plugin1, plugin2):
        plugin1.results = [dict(status="unknown")]
        plugin2.results = [dict(status="ok", groups=['group2', 'common'])]
        username, password = "user", "world"
        assert auth.get_auth_status((username, password)) == [
            'ok', username, ['common', 'group2']]
        assert plugin1.results == []  # all results used
        assert plugin2.results == []  # all results used
