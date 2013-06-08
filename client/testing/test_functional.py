
import pytest
import subprocess
from py import std

from test_devpi_server.test_views import TestUserThings, TestIndexThings

@pytest.fixture
def mapp(request, devpi, out_devpi):
    return Mapp(request, devpi, out_devpi)

class Mapp:
    def __init__(self, request, devpi, out_devpi):
        self.devpi = devpi
        self.out_devpi = out_devpi
        request.addfinalizer(self.cleanup)
        self.auth = (None, None)

    def cleanup(self):
        pw = getattr(self, "_rootpassword", None)
        if pw:
            if self.auth[0] != "root":
                self.login("root", pw)
            self.change_password("root", "")

    def delete_user(self, user, code=200):
        self.devpi("user", "--delete", user, code=code)

    def login_root(self):
        self.login("root", "")

    def login(self, user="root", password="", code=201):
        self.devpi("login", user, "--password", password, code=code)
        self.auth = (user, password)

    def getuserlist(self):
        result = self.out_devpi("user", "-l")
        return [x for x in result.outlines if x.strip()]

    def get_config(self, path, code=200):
        result = self.out_devpi("config", path, code=code)
        return std.json.loads(result.stdout.str())

    def getindexlist(self):
        result = self.out_devpi("index", "-l")
        return [x for x in result.outlines if x.strip()]

    def change_password(self, user, password):
        auth = getattr(self, "auth", None)
        if auth is None or auth[0] != user and auth[0] != "root":
            raise ValueError("need to be logged as %r or root" % user)
        self.devpi("user", "-m", user, "password=%s" % password)
        if user == "root" and password != "":
            self._rootpassword = password

    def create_user(self, user, password, email="hello@example.com", code=201):
        self.devpi("user", "-c", user, "password=%s" % password,
                   "email=%s" % email, code=code)

    def modify_user(self, user, password, email="hello@example.com", code=200):
        self.devpi("user", "-c", user, "password=%s" % password,
                   "email=%s" % email, code=code)

    def create_and_login_user(self, user="someuser", password="123"):
        self.create_user(user, password)
        self.login(user, password)

    def create_index(self, indexname, code=201):
        #user, password = self.auth
        self.devpi("index", "-c", indexname, code=code)

    def create_project(self, indexname, code=201):
        pytest.xfail(reason="no way to create project via command line yet")



