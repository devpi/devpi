
import pytest
from py import std
import time

from test_devpi_server.functional import TestUserThings, TestIndexThings # noqa
from test_devpi_server.functional import MappMixin

@pytest.fixture
def mapp(request, devpi, out_devpi):
    return Mapp(request, devpi, out_devpi)

class Mapp(MappMixin):
    _usercount = 10
    def __init__(self, request, devpi, out_devpi):
        self.devpi = devpi
        self.out_devpi = out_devpi
        request.addfinalizer(self.cleanup)
        self.auth = (None, None)
        self.current_stage = ""

    def _getindexname(self, indexname):
        if indexname is None:
            indexname = self.current_stage
        assert indexname
        return indexname

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

    def use(self, indexname):
        assert indexname.count("/") == 1, indexname
        self.devpi("use", indexname)
        self.current_stage = indexname
        self.api = self.getapi()

    def login(self, user="root", password="", code=200):
        self.devpi("login", user, "--password", password, code=code)
        self.auth = (user, password)

    def getuserlist(self):
        result = self.out_devpi("user", "-l")
        return [x for x in result.outlines if x.strip()]

    def getjson(self, path, code=200):
        result = self.out_devpi("getjson", path, code=code)
        if code == 200:
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
                if name == "volatile":
                    params.append("%s=%s" % (name, bool(val)))
        return params

    def create_index(self, indexname, indexconfig=None, code=200):
        #user, password = self.auth
        params = self._indexconfig_to_cmdline_keyvalue(indexconfig)
        self.out_devpi("index", "-c", indexname, *params, code=code)

    def delete_index(self, indexname, code=201):
        self.out_devpi("index", "--delete", indexname, code=code)

    def set_acl(self, acls, code=200, indexname=None):
        #user, password = self.auth
        indexname = self._getindexname(indexname)
        if isinstance(acls, list):
            acls = ",".join(acls)
        self.devpi("index", indexname, "acl_upload=%s" % acls, code=200)

    def set_uploadtrigger_jenkins(self, url, indexname=None):
        if indexname is None:
            self.devpi("index", "uploadtrigger_jenkins=%s" % url, code=200)
        else:
            self.devpi("index", indexname,
                       "uploadtrigger_jenkins=%s" % url, code=200)

    def get_acl(self, code=200, indexname=None):
        indexname = self._getindexname(indexname)
        result = self.out_devpi("index", indexname)
        for line in result.outlines:
            line = line.strip()
            parts = line.split("acl_upload=", 1)
            if len(parts) == 2:
                return parts[1].split(",")
        return  []

    def create_project(self, projectname, code=201, indexname=None):
        pytest.xfail(reason="no way to create project via command line yet")


def test_logoff(mapp):
    mapp.login()
    mapp.logoff()
    mapp.logoff()

def test_getjson(out_devpi):
    result = out_devpi("getjson", "/", "-v")
    assert "X-DEVPI-API-VERSION" in result.stdout.str()

class TestUserManagement:
    """ This class tests the user sub command of devpi
    """

    @pytest.fixture
    def new_user_id(self, request, gen, mapp):
        user_id = "tmp_%s_%s"  %(gen.user(), str(time.time()))
        def del_tmp_user():
            try:
                mapp.delete_user(user = user_id, code=201)
            except:
                pass
        request.addfinalizer(del_tmp_user)
        return user_id

    @pytest.fixture
    def existing_user_id(self, request, new_user_id, mapp):
        """ Create a temporary user - will be deleted when the
        fixture is finalized"""
        mapp.create_user(user=new_user_id, password=1234,
                         email=new_user_id + "@example.com", code=201)
        return new_user_id

    @pytest.fixture
    def user_list(self, mapp, port_of_liveserver):
        """ This fixture gets the list of user via getjson"""
        return mapp.getjson(
            "http://localhost:%s" % port_of_liveserver)['result'].keys()

    def test_create_new_user(self, mapp, new_user_id):
        """ Verifies that a new user can be created"""

        mapp.create_user(user=new_user_id, password=1234,
                         email=new_user_id + "@example.com", code=201)
        mapp.out_devpi('user', '-l').stdout.fnmatch_lines(new_user_id)

    def test_duplicate_user(self, mapp, existing_user_id):
        """ Verifies that a new user can be created"""

        mapp.create_user(user=existing_user_id, password=1234,
                         email=existing_user_id + "@example.com", code=409)

    def test_user_list(self, mapp, user_list):
        """ Obtain the list of users via getjson and verify that
        it matches what is returned by devpi user -l
        """
        user_list = set(user_list)
        res = set(mapp.getuserlist())
        assert len(user_list) == len(res) and user_list.issubset(res)

    def test_unauthorized_mod(self, mapp, existing_user_id):
        """ Verify that if current user is logged off,
        modifications can not be done"""
        mapp.logoff()
        mapp.modify_user(user=existing_user_id, password=id(self), code=401)

    def test_mod_password(self, mapp, existing_user_id):
        """ Verify that password change is effective"""
        mapp.logoff()
        mapp.login(user=existing_user_id, password="1234")
        mapp.modify_user(user = existing_user_id, password = id(self))
        # Verify that the password was indeed changed.
        mapp.logoff()
        mapp.login(user=existing_user_id,
                   password="1234", code = 401)
        mapp.login(user=existing_user_id, password=id(self))

    def test_mod_email(self, mapp, existing_user_id, port_of_liveserver):
        """ Verify that email change is effective"""
        mapp.logoff()
        mapp.login(user=existing_user_id, password="1234")
        email_address = existing_user_id + '_' + str(id(self)) + "@devpi.net"
        mapp.modify_user(user=existing_user_id, email=email_address)
        # Verify that the email was indeed changed.
        json = mapp.getjson("http://localhost:%s" % port_of_liveserver)
        assert json['result'][existing_user_id]['email'] == email_address

    def test_mod_combined(self, mapp, existing_user_id, port_of_liveserver):
        """ Verify that password change is effective"""
        mapp.logoff()
        mapp.login(user=existing_user_id, password="1234")
        email_address = existing_user_id + '_' + str(id(self)) + "@devpi.net"
        mapp.modify_user(user=existing_user_id, password=id(self),
                         email=email_address)

        # Verify that the email was changed.
        json = mapp.getjson("http://localhost:%s" % port_of_liveserver)
        assert json['result'][existing_user_id]['email'] == email_address

        # Verify that the password was indeed changed.
        mapp.logoff()
        mapp.login(user=existing_user_id, password="1234", code=401)
        mapp.login(user=existing_user_id, password=id(self))

    def test_delete_root_forbidden(self, mapp):
        """ Verifies that the root user can not be deleted.

        This test is not implemented correctly because of issue #26.

        Technically, mapp.delete_user(user = "root", code=403) should
        raise an exception if the operation did not fail with the
        appropriate error code. tx
        """
        mapp.login_root()
        mapp.delete_user(user="root", code=403)
