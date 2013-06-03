
import pytest
import subprocess
from py import std

from test_devpi_server.test_views import TestUserThings, TestIndexThings

@pytest.fixture
def mapp(request, devpi, out_devpi):
    return Mapp(devpi, out_devpi)

class Mapp:
    def __init__(self, devpi, out_devpi):
        self.devpi = devpi
        self.out_devpi = out_devpi

    def delete_user(self, user):
        self.devpi("user", "-d", user)

    def delete_user_fails(self, user):
        with pytest.raises(SystemExit):
            self.devpi("user", "-d", user)


    def login(self, user="root", password=""):
        self.devpi("login", user, "--password", password)
        self.auth = (user, password)

    def login_fails(self, user="root", password=""):
        with pytest.raises(SystemExit):
            self.devpi("login", user, "--password", password)

    def getuserlist(self):
        result = self.out_devpi("user", "-l")
        return [x for x in result.outlines if x.strip()]

    def change_password(self, user, password):
        auth = getattr(self, "auth", None)
        if auth is None or auth[0] != user and auth[0] != "root":
            raise ValueError("need to be logged as %r or root" % user)
        self.devpi("user", "-m", user, "password=%s" % password)

    def create_user(self, user, password, email="hello@example.com"):
        self.devpi("user", "-c", user, "password=%s" % password,
                   "email=%s" % email)

    def create_user_fails(self, user, password, email="hello@example.com"):
        with pytest.raises(SystemExit):
            self.devpi("user", "-c", user, "password=%s" % password,
                       "email=%s" % email)

    def create_and_login_user(self, user="someuser"):
        self.create_user(user, "123")
        self.login(user, "123")

    def create_index(self, indexname):
        user, password = self.auth
        self.devpi("index", "-c", indexname)
