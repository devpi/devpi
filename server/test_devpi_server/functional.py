
class API:
    def __init__(self, d):
        self.__dict__ = d

class MappMixin:
    _usercount = 0

    def create_and_use(self, stagename=None, password="123", indexconfig=None):
        if stagename is None:
            stagename = self.get_new_stagename()
        user, index = stagename.split("/")
        self.create_and_login_user(user, password=password)
        self.create_index(index, indexconfig=indexconfig)
        self.use(stagename)
        self.api.user = user
        self.api.password = password
        self.api.stagename = stagename
        return self.api

    def get_new_stagename(self):
        self._usercount += 1
        return "user%s/dev" % self._usercount

    def getapi(self, relpath="/"):
        path = relpath.strip("/")
        if not path:
            path = "/+api"
        else:
            path = "/%s/+api" % path
        return API(self.getjson(path)["result"])


class TestUserThings:
    def test_root_cannot_modify_unknown_user(self, mapp):
        mapp.login_root()
        mapp.modify_user("/user", password="123", email="whatever",
                         code=404)

    def test_root_is_refused_with_wrong_password(self, mapp):
        mapp.login("root", "123123", code=401)

    def test_root_not_deleteable(self, mapp):
        mapp.login_root()
        mapp.delete_user("root", code=403)

    def test_create_and_delete_user(self, mapp):
        password = "somepassword123123"
        assert "hello" not in mapp.getuserlist()
        mapp.create_user("hello", password)
        mapp.create_user("hello", password, code=409)
        assert "hello" in mapp.getuserlist()
        mapp.login("hello", "qweqwe", code=401)
        mapp.login("hello", password)
        mapp.delete_user("hello")
        mapp.login("hello", password, code=401)
        assert "hello" not in mapp.getuserlist()

    def test_create_and_delete_user_no_email(self, mapp):
        name = "hello_noemail"
        password = "somepassword123123"
        assert name not in mapp.getuserlist()
        mapp.create_user(name, password, email=None)
        mapp.create_user(name, password, code=409)
        assert name in mapp.getuserlist()
        mapp.login(name, "qweqwe", code=401)
        mapp.login(name, password)
        mapp.delete_user(name)
        mapp.login(name, password, code=401)
        assert name not in mapp.getuserlist()

    def test_delete_not_existent_user(self, mapp):
        mapp.login("root", "")
        mapp.delete_user("qlwkje", code=404)

    def test_password_setting_admin(self, mapp):
        mapp.login("root", "")
        mapp.change_password("root", "p1oi2p3i")
        mapp.login("root", "p1oi2p3i")

class TestIndexThings:

    def test_getjson_non_existent(self, mapp):
        mapp.getjson("/whatever/index", 404)

    def test_create_and_delete_index(self, mapp):
        mapp.create_and_login_user()
        indexname = mapp.auth[0] + "/dev"
        assert indexname not in mapp.getindexlist()
        mapp.create_index("dev")
        assert indexname in mapp.getindexlist()
        mapp.delete_index("dev")
        assert indexname not in mapp.getindexlist()

    def test_create_index_auth_deleted(self, mapp):
        mapp.create_and_login_user("ci1")
        mapp.delete_user("ci1")
        mapp.create_index("ci1/dev", code=404)

    def test_create_index__not_exists(self, mapp):
        mapp.create_index("not_exists/dev", code=404)

    def test_create_index_base_not_exists(self, mapp):
        indexconfig = dict(bases=("not/exists",))
        mapp.login_root()
        m = mapp.create_index("root/hello", indexconfig=indexconfig, code=400)
        if m:  # only server-side mapp returns messages
            assert "not/exists" in m

    def test_create_index_base_empty(self, mapp):
        indexconfig = dict(bases=())
        mapp.login_root()
        mapp.create_index("root/empty", indexconfig=indexconfig, code=200)
        data = mapp.getjson("/root/empty")
        assert not data["result"]["bases"]

    def test_create_index_base_normalized(self, mapp):
        indexconfig = dict(bases=("/root/pypi",))
        mapp.login_root()
        mapp.create_index("root/hello", indexconfig=indexconfig,
                          code=200)

    def test_create_index_base_invalid(self, mapp):
        mapp.login_root()
        indexconfig = dict(bases=("/root/dev/123",))
        m = mapp.create_index("root/newindex1",
                              indexconfig=indexconfig, code=400)
        if m:
            assert "root/dev/123" in m

    def test_create_index_default_allowed(self, mapp):
        mapp.login_root()
        mapp.create_index("root/test1")
        mapp.login("root", "")
        mapp.change_password("root", "asd")
        mapp.create_and_login_user("newuser1")
        mapp.create_index("root/test2", code=401)

    def test_create_index_and_acls(self, mapp):
        username = "newuser2"
        mapp.create_user(username, "password")
        mapp.login_root()
        mapp.create_index("test2")
        mapp.use("root/test2")
        mapp.set_acl([username])
        assert username in mapp.get_acl()
        mapp.set_acl("root/test2", [])
        assert username not in mapp.get_acl()

    def test_create_index_with_jenkinsurl(self, mapp):
        url = "http://localhost:8080/"
        mapp.login_root()
        mapp.create_index("root/test3")
        mapp.use("root/test3")
        mapp.set_uploadtrigger_jenkins(url)
        data = mapp.getjson("/root/test3")
        assert data["result"]["uploadtrigger_jenkins"] == url

    def test_config_get_user_empty(self, mapp):
        mapp.getjson("/user", code=404)

    def test_create_user_and_config_gets(self, mapp):
        assert mapp.getjson("/")["type"] == "list:userconfig"
        mapp.create_and_login_user("cuser1")
        data = mapp.getjson("/cuser1")
        assert data["type"] == "userconfig"
        data = mapp.getjson("/cuser1/")
        assert data["type"] == "list:indexconfig"

    def test_create_index_and_config_gets(self, mapp):
        mapp.create_and_login_user("cuser2")
        mapp.create_index("dev")
        assert mapp.getjson("/cuser2/dev")["type"] == "indexconfig"
        assert mapp.getjson("/cuser2/dev/")["type"] == "list:projectconfig"

    def test_non_volatile_cannot_be_deleted(self, mapp):
        mapp.create_and_login_user("cuser4")
        mapp.create_index("dev", indexconfig={"volatile": False})
        mapp.delete_index("dev", code=403)
        mapp.delete_user("cuser4", code=403)

