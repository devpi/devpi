import py
import pytest
from devpi_server.auth import *

pytestmark = [pytest.mark.writetransaction]

class TestAuth:
    @pytest.fixture
    def auth(self, model):
        from devpi_server.views import Auth
        return Auth(model, "qweqwe")

    def test_auth_direct(self, model, auth):
        model.create_user("user", password="world")
        assert auth._get_auth_groups("user", "world") == []

    def test_proxy_auth(self, model, auth):
        model.create_user("user", password="world")
        assert auth.new_proxy_auth("user", "wrongpass") is None
        assert auth.new_proxy_auth("uer", "wrongpass") is None
        res = auth.new_proxy_auth("user", "world")
        assert "password" in res and "expiration" in res
        assert auth._get_auth_groups("user", res["password"]) == []

    def test_proxy_auth_expired(self, model, auth, monkeypatch):
        username, password = "user", "world"

        model.create_user(username, password=password)
        proxy = auth.new_proxy_auth(username, password)

        def r(*args, **kw): raise py.std.itsdangerous.SignatureExpired("123")
        monkeypatch.setattr(auth.serializer, "loads", r)

        res = auth._get_auth_groups(username, proxy["password"], raising=False)
        assert res is None
        with pytest.raises(auth.Expired):
            auth._get_auth_groups(username, proxy["password"])
        assert auth.get_auth_status((username, proxy["password"])) == ["expired", username]

    def test_auth_status_no_auth(self, auth):
        assert auth.get_auth_status(None) == ["noauth", ""]

    def test_auth_status_no_user(self, auth):
        assert auth.get_auth_status(("user1", "123")) == ["nouser", "user1"]

    def test_auth_status_proxy_user(self, model, auth):
        username, password = "user", "world"
        model.create_user(username, password)
        proxy = auth.new_proxy_auth(username, password)
        assert auth.get_auth_status((username, proxy["password"])) == \
               ["ok", username]

def test_newsalt():
    assert newsalt() != newsalt()

def test_hash_verification():
    salt, hash = crypt_password("hello")
    assert verify_password("hello", hash, salt)
    assert not verify_password("xy", hash, salt)
    assert not verify_password("hello", hash, newsalt())
