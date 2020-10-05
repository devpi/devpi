from io import BytesIO
import json
import py
import pytest
import requests
import tarfile
import time

from .functional import TestUserThings, TestIndexThings # noqa
try:
    from .functional import TestMirrorIndexThings  # noqa
except ImportError:
    # when testing with older devpi-server
    class TestMirrorIndexThings:
        def test_mirror_things(self):
            pytest.skip(
                "Couldn't import TestMirrorIndexThings from devpi server tests.")
try:
    from .functional import TestIndexPushThings  # noqa
except ImportError:
    # when testing with older devpi-server
    class TestIndexPushThings:
        def test_mirror_things(self):
            pytest.skip(
                "Couldn't import TestIndexPushThings from devpi server tests.")
from .functional import MappMixin


@pytest.fixture
def mapp(request, devpi, out_devpi, tmpdir):
    return Mapp(request, devpi, out_devpi, tmpdir)


class Mapp(MappMixin):
    _usercount = 10

    def __init__(self, request, devpi, out_devpi, tmpdir):
        self.devpi = devpi
        self.out_devpi = out_devpi
        request.addfinalizer(self.cleanup)
        self.auth = (None, None)
        self.current_stage = ""
        self.tmpdir = tmpdir

    def _getindexname(self, indexname):
        if indexname is None:
            indexname = self.current_stage
        assert indexname
        return indexname

    def makepkg(self, basename, content, name, version):
        s = BytesIO()
        pkg_info = '\n'.join([
            "Metadata-Version: 1.1",
            "Name: %s" % name,
            "Version: %s" % version]).encode('utf-8')
        tf = tarfile.open(basename, mode='w:gz', fileobj=s)
        tinfo = tarfile.TarInfo('PKG-INFO')
        tinfo.size = len(pkg_info)
        tf.addfile(tinfo, BytesIO(pkg_info))
        tinfo = tarfile.TarInfo('content')
        tinfo.size = len(content)
        tf.addfile(tinfo, BytesIO(content))
        tf.close()
        return s.getvalue()

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

    def logout(self, code=None):
        self.devpi("logout", code=code)

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
            return json.loads(result.stdout.str())

    def getindexlist(self):
        result = self.out_devpi("index", "-l")
        return [x for x in result.outlines if x.strip()]

    def getpkglist(self):
        result = self.out_devpi("list")
        return [x for x in result.outlines if x.strip()]

    def getreleaseslist(self, name, code=200):
        result = self.out_devpi("list", name, code=code)
        return [x for x in result.outlines if x.strip()]

    def downloadrelease(self, code, url):
        r = requests.get(url)
        if isinstance(code, tuple):
            assert r.status_code in code
        else:
            assert r.status_code == code
        if r.status_code < 300:
            return r.content
        return r.json()

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
                elif name == "volatile":
                    params.append("%s=%s" % (name, bool(val)))
                else:
                    params.append("%s=%s" % (name, val))
        return params

    def create_index(self, indexname, indexconfig=None, code=200):
        #user, password = self.auth
        params = self._indexconfig_to_cmdline_keyvalue(indexconfig)
        self.out_devpi("index", "-c", indexname, *params, code=code)

    def delete_index(self, indexname, code=201):
        self.out_devpi("index", "--delete", indexname, code=code)

    def modify_index(self, index, indexconfig, code=200):
        import json
        jsonfile = self.tmpdir.join("jsonfile")
        jsonfile.write(json.dumps(indexconfig))
        self.devpi("patchjson", "/" + index, jsonfile, code=code)

    def set_acl(self, acls, code=200, indexname=None):
        #user, password = self.auth
        indexname = self._getindexname(indexname)
        if isinstance(acls, list):
            acls = ",".join(acls)
        self.devpi("index", indexname, "acl_upload=%s" % acls, code=200)

    def set_custom_data(self, data, indexname=None):
        return self.set_key_value("custom_data", data, indexname=indexname)

    def set_key_value(self, key, value, indexname=None):
        if indexname is None:
            self.devpi("index", "%s=%s" % (key, value), code=200)
        else:
            self.devpi("index", indexname,
                       "%s=%s" % (key, value), code=200)

    def set_uploadtrigger_jenkins(self, *args, **kwargs):
        # called when we run client tests against server-2.1
        pytest.skip("jenkins functionality moved out to pytest-jenkins")

    def set_indexconfig_option(self, key, value, indexname=None):
        if indexname is None:
            self.devpi("index", "%s=%s" % (key, value), code=200)
        else:
            self.devpi("index", indexname,
                       "%s=%s" % (key, value), code=200)

    def set_mirror_whitelist(self, whitelist, indexname=None):
        if indexname is None:
            self.devpi("index", "mirror_whitelist=%s" % whitelist, code=200)
        else:
            self.devpi("index", indexname,
                       "mirror_whitelist=%s" % whitelist, code=200)

    def get_acl(self, code=200, indexname=None):
        indexname = self._getindexname(indexname)
        result = self.out_devpi("index", indexname)
        for line in result.outlines:
            line = line.strip()
            parts = line.split("acl_upload=", 1)
            if len(parts) == 2:
                return [x for x in parts[1].split(",") if x]
        return []

    def get_mirror_whitelist(self, code=200, indexname=None):
        indexname = self._getindexname(indexname)
        result = self.out_devpi("index", indexname)
        for line in result.outlines:
            line = line.strip()
            parts = line.split("mirror_whitelist=", 1)
            return parts[1].split(",")

    def upload_file_pypi(self, basename, content,
                         name=None, version=None):
        assert py.builtin._isbytes(content)
        pkg = self.tmpdir.join(basename)
        pkg.write_binary(content)
        self.devpi('upload', pkg.strpath)

    def push(self, name, version, index, indexname=None, code=200):
        self.devpi('push', '%s==%s' % (name, version), index, code=code)

    def create_project(self, projectname, code=201, indexname=None):
        pytest.xfail(reason="no way to create project via command line yet")


def test_logoff(mapp):
    mapp.login()
    mapp.logoff()
    mapp.logoff()


def test_logout(mapp):
    mapp.login()
    mapp.logout()
    mapp.logout()


def test_getjson(out_devpi):
    result = out_devpi("getjson", "/", "-v")
    assert "X-DEVPI-API-VERSION" in result.stdout.str()


def test_switch_preserves_auth(out_devpi, url_of_liveserver, url_of_liveserver2):
    import re
    result1 = out_devpi("use", url_of_liveserver)
    (url1, user1) = re.search(
        r'(https?://.+?)\s+\(logged in as (.+?)\)', result1.stdout.str()).groups()
    result2 = out_devpi("use", url_of_liveserver2)
    url2 = re.search(
        r'(https?://.+?)\s+\(not logged in\)', result2.stdout.str()).group(1)
    assert url2 != url1
    out_devpi("user", "-c", user1, "password=123", "email=123")
    out_devpi("login", user1, "--password", "123")
    out_devpi("index", "-c", "dev")
    result3 = out_devpi("use", "dev")
    (url3, user3) = re.search(
        r'(https?://.+?)\s+\(logged in as (.+?)\)', result3.stdout.str()).groups()
    assert user3 == user1
    assert url3.startswith(url2)
    result4 = out_devpi("use", url_of_liveserver)
    (url4, user4) = re.search(
        r'(https?://.+?)\s+\(logged in as (.+?)\)', result4.stdout.str()).groups()
    assert user4 == user1
    assert url4 == url1


@pytest.fixture
def new_user_id(gen, mapp):
    """Create a new user id.

       In case it was used to create a user, that user will be deleted on
       fixture tear down.
    """
    user_id = "tmp_%s_%s" % (gen.user(), str(time.time()))
    yield user_id
    try:
        mapp.delete_user(user=user_id, code=201)
    except:  # noqa
        # We need a bare except here, because there are exceptions from
        # pytest and other places which don't derive from Exception and
        # listing them all would be long and not future proof
        pass


@pytest.fixture
def existing_user_id(new_user_id, mapp):
    """Create a temporary user."""
    mapp.create_user(
        user=new_user_id, password=1234,
        email=new_user_id + "@example.com")
    return new_user_id


class TestUserManagement:
    """ This class tests the user sub command of devpi
    """

    @pytest.fixture
    def user_list(self, mapp, url_of_liveserver):
        """ This fixture gets the list of user via getjson"""
        return mapp.getjson(url_of_liveserver)['result'].keys()

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
        mapp.modify_user(user=existing_user_id, password=id(self), code=403)

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

    def test_mod_email(self, mapp, existing_user_id, url_of_liveserver):
        """ Verify that email change is effective"""
        mapp.logoff()
        mapp.login(user=existing_user_id, password="1234")
        email_address = existing_user_id + '_' + str(id(self)) + "@devpi.net"
        mapp.modify_user(user=existing_user_id, email=email_address)
        # Verify that the email was indeed changed.
        json = mapp.getjson(url_of_liveserver)
        assert json['result'][existing_user_id]['email'] == email_address

    def test_mod_combined(self, mapp, existing_user_id, url_of_liveserver):
        """ Verify that password change is effective"""
        mapp.logoff()
        mapp.login(user=existing_user_id, password="1234")
        email_address = existing_user_id + '_' + str(id(self)) + "@devpi.net"
        mapp.modify_user(user=existing_user_id, password=id(self),
                         email=email_address)

        # Verify that the email was changed.
        json = mapp.getjson(url_of_liveserver)
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


class TestAddRemoveSettings:
    def test_add_remove_index_list_setting(self, mapp, existing_user_id, server_version, url_of_liveserver):
        from pkg_resources import parse_version
        jsonpatch_devpi_version = parse_version("4.7.2dev")
        if server_version < jsonpatch_devpi_version:
            pytest.skip("devpi-server without key value parsing support")
        mapp.login(user=existing_user_id, password="1234")
        indexname = '%s/dev' % existing_user_id
        indexurl = url_of_liveserver.joinpath(indexname)
        mapp.create_index(indexname)
        json = mapp.getjson(indexurl)
        assert json['result']['acl_upload'] == [existing_user_id]
        mapp.devpi("index", indexname, "acl_upload+=foo")
        json = mapp.getjson(indexurl)
        assert 'foo' in json['result']['acl_upload']
        mapp.devpi("index", indexname, "acl_upload-=foo")
        json = mapp.getjson(indexurl)
        assert json['result']['acl_upload'] == [existing_user_id]
