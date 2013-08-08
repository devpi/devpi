
import pytest
import subprocess
from py import std

from test_devpi_server.functional import TestUserThings, TestIndexThings

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

    def logoff(self, code=None):
        self.devpi("logoff", code=code)

    def login(self, user="root", password="", code=200):
        self.devpi("login", user, "--password", password, code=code)
        self.auth = (user, password)

    def getuserlist(self):
        result = self.out_devpi("user", "-l")
        assert "200" not in result.stdout.str()
        return [x for x in result.outlines if x.strip()]

    def getjson(self, path, code=200):
        result = self.out_devpi("getjson", path, code=code)
        if code == 200:
            return std.json.loads(result.stdout.str())

    def getindexlist(self):
        result = self.out_devpi("index", "-l")
        assert "200" not in result.stdout.str()
        return [x for x in result.outlines if x.strip()]

    def change_password(self, user, password):
        auth = getattr(self, "auth", None)
        if auth is None or auth[0] != user and auth[0] != "root":
            raise ValueError("need to be logged as %r or root" % user)
        self.devpi("user", "-m", user, "password=%s" % password)
        if user == "root" and password != "":
            self._rootpassword = password

    def create_user(self, user, password=None, email=None, code=201):
        self._usercommand("-c", user, password, email, code=code)

    def modify_user(self, user, password=None, email=None, code=200):
        self._usercommand("-m", user, password, email, code=code)

    def _usercommand(self, flag, user, password, email, code):
        args = []
        if password:
            args.append("password=%s" % password)
        if email:
            args.append("email=%s" % email)
        self.devpi("user", flag, user, *args, code=code)

    def create_and_login_user(self, user="someuser", password="123"):
        self.create_user(user, password)
        self.login(user, password)

    def _indexconfig_to_cmdline_keyvalue(self, indexconfig):
        params = []
        if indexconfig:
            for name, val in indexconfig.items():
                if name == "bases":
                    params.append("%s=%s" % (name, ",".join(val)))
        return params

    def create_index(self, indexname, indexconfig=None, code=200):
        #user, password = self.auth
        params = self._indexconfig_to_cmdline_keyvalue(indexconfig)
        self.out_devpi("index", "-c", indexname, *params, code=code)

    def set_acl(self, indexname, acls, code=200):
        #user, password = self.auth
        if isinstance(acls, list):
            acls = ",".join(acls)
        self.devpi("index", indexname, "acl_upload=%s" % acls, code=200)

    def set_uploadtrigger_jenkins(self, indexname, url):
        self.devpi("index", indexname,
                   "uploadtrigger_jenkins=%s" % url, code=200)

    def get_acl(self, indexname, code=200):
        result = self.out_devpi("index", indexname)
        for line in result.outlines:
            line = line.strip()
            parts = line.split("acl_upload=", 1)
            if len(parts) == 2:
                return parts[1].split(",")
        return  []

    def create_project(self, indexname, code=201):
        pytest.xfail(reason="no way to create project via command line yet")




def test_logoff(mapp):
    mapp.login()
    mapp.logoff()
    mapp.logoff()

