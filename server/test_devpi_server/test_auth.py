import py
import pytest
from devpi_server.auth import *

class TestAuth:
    @pytest.fixture
    def auth(self, xom):
        from devpi_server.views import Auth
        return Auth(xom, "qweqwe")

    def test_no_auth(self, auth):
        assert auth.get_auth_user(None) is None

    def test_auth_direct(self, xom, auth):
        user = xom.get_user("user")
        user.create(password="world")
        assert auth.get_auth_user(("user", "world")) == "user"

    def test_proxy_auth(self, xom, auth):
        user = xom.get_user("user")
        user.create(password="world")
        assert auth.new_proxy_auth("user", "wrongpass") is None
        assert auth.new_proxy_auth("uer", "wrongpass") is None
        res = auth.new_proxy_auth("user", "world")
        assert "password" in res and "expiration" in res
        assert auth.get_auth_user(("user", res["password"]))

    def test_proxy_auth_expired(self, xom, auth, monkeypatch):
        username, password = "user", "world"

        user = xom.get_user(username)
        user.create(password=password)
        proxy = auth.new_proxy_auth(username, password)

        def r(*args): raise py.std.itsdangerous.SignatureExpired("123")
        monkeypatch.setattr(auth.signer, "unsign", r)

        newauth = (username, proxy["password"])
        res = auth.get_auth_user(newauth, raising=False)
        assert res is None
        with pytest.raises(auth.Expired):
            auth.get_auth_user(newauth)
        assert auth.get_auth_status(newauth) == ["expired", username]

    def test_auth_status_no_auth(self, auth):
        assert auth.get_auth_status(None) == ["noauth", ""]

    def test_auth_status_no_user(self, auth):
        assert auth.get_auth_status(("user1", "123")) == ["nouser", "user1"]

    def test_auth_status_proxy_user(self, xom, auth):
        username, password = "user", "world"
        user = xom.get_user(username)
        user.create(password)
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
