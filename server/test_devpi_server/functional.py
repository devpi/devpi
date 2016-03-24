import pytest


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
        mapp.modify_user("user", password="123", email="whatever",
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
        # if this test fails after the first change_password, subsequent tests
        # might fail as well with an unauthorized error
        mapp.login("root", "")
        mapp.change_password("root", "p1oi2p3i")
        mapp.login("root", "p1oi2p3i")
        mapp.change_password("root", "")


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

    def test_pypi_index_attributes(self, mapp):
        mapp.login_root()
        data = mapp.getjson("/root/pypi")
        res = data["result"]
        res.pop("projects")
        assert res == {
            "type": "mirror",
            "volatile": False,
            "title": "PyPI",
            "mirror_url": "https://pypi.python.org/simple/",
            "mirror_web_url_fmt": "https://pypi.python.org/pypi/{name}"}

    def test_create_index_base_empty(self, mapp):
        indexconfig = dict(bases="")
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
        mapp.create_and_login_user("newuser1")
        mapp.create_index("root/test2", code=403)

    def test_create_index_and_acls(self, mapp):
        username = "newuser2"
        mapp.create_user(username, "password")
        mapp.login_root()
        mapp.create_index("test2")
        mapp.use("root/test2")
        mapp.set_acl([username])
        assert mapp.get_acl() == [username]
        mapp.set_acl([])
        assert mapp.get_acl() == []
        mapp.set_acl([':anonymous:'])
        assert mapp.get_acl() == [':ANONYMOUS:']

    def test_create_with_invalid_type(self, mapp):
        mapp.login_root()
        indexconfig = dict(type="foo")
        mapp.create_index("root/newindex1",
                          indexconfig=indexconfig, code=400)

    def test_modify_type_not_allowed(self, mapp):
        mapp.login_root()
        mapp.create_index("root/newindex1")
        res = mapp.getjson("/root/newindex1")["result"]
        res["type"] = "foo"
        mapp.modify_index("root/newindex1", res, code=400)
        res["type"] = "mirror"
        mapp.modify_index("root/newindex1", res, code=400)

    def test_config_get_user_empty(self, mapp):
        mapp.getjson("/user", code=404)

    def test_create_user_and_config_gets(self, mapp):
        assert mapp.getjson("/")["type"] == "list:userconfig"
        mapp.create_and_login_user("cuser1")
        data = mapp.getjson("/cuser1")
        assert data["type"] == "userconfig"

    def test_create_index_and_config_gets(self, mapp):
        mapp.create_and_login_user("cuser2")
        mapp.create_index("dev")
        res =  mapp.getjson("/cuser2/dev")
        assert res["type"] == "indexconfig"
        assert res["result"]["projects"] == []

    def test_non_volatile_cannot_be_deleted(self, mapp):
        mapp.create_and_login_user("cuser4")
        mapp.create_index("dev", indexconfig={"volatile": False})
        mapp.delete_index("dev", code=403)
        mapp.delete_user("cuser4", code=403)

    def test_push_existing_to_volatile(self, mapp):
        username = 'puser1'
        mapp.create_and_login_user("%s" % username)
        mapp.create_index("prod", indexconfig={"volatile": True})
        mapp.create_index("dev", indexconfig={"volatile": True, "bases": ['%s/prod' % username]})
        mapp.use("%s/prod" % username)
        content1 = mapp.makepkg("hello-1.0.tar.gz", b"content1", "hello", "1.0")
        mapp.upload_file_pypi("hello-1.0.tar.gz", content1, "hello", "1.0")
        mapp.use("%s/dev" % username)
        content2 = mapp.makepkg("hello-1.0.tar.gz", b"content2", "hello", "1.0")
        mapp.upload_file_pypi("hello-1.0.tar.gz", content2, "hello", "1.0")
        mapp.push("hello", "1.0", "%s/prod" % username)
        res = mapp.getjson("/%s/prod/hello" % username)
        assert list(res['result'].keys()) == ['1.0']
        link, = res['result']['1.0']['+links']
        assert len(link['log']) == 3
        assert link['log'][0]['what'] == 'overwrite'
        assert link['log'][0]['count'] == 1
        assert link['log'][1]['what'] == 'upload'
        assert link['log'][1]['dst'] == '%s/dev' % username
        res = mapp.getjson("/%s/dev/hello" % username)
        assert list(res['result'].keys()) == ['1.0']
        link, = res['result']['1.0']['+links']
        assert len(link['log']) == 1
        assert link['log'][0]['what'] == 'upload'
        assert link['log'][0]['dst'] == '%s/dev' % username

    def test_push_existing_to_nonvolatile(self, mapp):
        username = 'puser2'
        mapp.create_and_login_user("%s" % username)
        mapp.create_index("prod", indexconfig={"volatile": False})
        mapp.create_index("dev", indexconfig={"volatile": True, "bases": ['%s/prod' % username]})
        mapp.use("%s/prod" % username)
        content1 = mapp.makepkg("hello-1.0.tar.gz", b"content1", "hello", "1.0")
        mapp.upload_file_pypi("hello-1.0.tar.gz", content1, "hello", "1.0")
        mapp.use("%s/dev" % username)
        content2 = mapp.makepkg("hello-1.0.tar.gz", b"content2", "hello", "1.0")
        mapp.upload_file_pypi("hello-1.0.tar.gz", content2, "hello", "1.0")
        mapp.push("hello", "1.0", "%s/prod" % username, code=409)
        res = mapp.getjson("/%s/prod/hello" % username)
        assert list(res['result'].keys()) == ['1.0']
        link, = res['result']['1.0']['+links']
        assert len(link['log']) == 1
        assert link['log'][0]['what'] == 'upload'
        assert link['log'][0]['dst'] == '%s/prod' % username
        res = mapp.getjson("/%s/dev/hello" % username)
        assert list(res['result'].keys()) == ['1.0']
        link, = res['result']['1.0']['+links']
        assert len(link['log']) == 1
        assert link['log'][0]['what'] == 'upload'
        assert link['log'][0]['dst'] == '%s/dev' % username

    def test_custom_data(self, mapp):
        mapp.create_and_login_user("cuser5")
        mapp.create_index("dev")
        mapp.use("cuser5/dev")
        res = mapp.getjson("/cuser5/dev")
        assert "custom_data" not in res["result"]
        mapp.set_key_value("custom_data", "foo")
        res = mapp.getjson("/cuser5/dev")
        assert res["result"]["custom_data"] == "foo"

    def test_title_description(self, mapp):
        mapp.create_and_login_user("cuser6")
        mapp.create_index("dev")
        mapp.use("cuser6/dev")
        res = mapp.getjson("/cuser6/dev")
        assert "title" not in res["result"]
        assert "description" not in res["result"]
        mapp.set_key_value("title", "foo")
        mapp.set_key_value("description", "bar")
        res = mapp.getjson("/cuser6/dev")
        assert res["result"]["title"] == "foo"
        assert res["result"]["description"] == "bar"

    def test_whitelist_setting(self, mapp):
        mapp.create_and_login_user("cuser7")
        mapp.create_index("dev")
        mapp.use("cuser7/dev")
        res = mapp.getjson("/cuser7/dev")['result']
        assert res['pypi_whitelist'] == []
        assert res['mirror_whitelist'] == []
        mapp.set_mirror_whitelist("foo")
        res = mapp.getjson("/cuser7/dev")['result']
        assert res['pypi_whitelist'] == []
        assert res['mirror_whitelist'] == ['foo']
        mapp.set_mirror_whitelist("foo,bar")
        res = mapp.getjson("/cuser7/dev")['result']
        assert res['pypi_whitelist'] == []
        assert res['mirror_whitelist'] == ['foo', 'bar']
        mapp.set_mirror_whitelist("he_llo")
        res = mapp.getjson("/cuser7/dev")['result']
        assert res['pypi_whitelist'] == []
        assert res['mirror_whitelist'] == ['he-llo']
        mapp.set_mirror_whitelist("he_llo,Django")
        res = mapp.getjson("/cuser7/dev")['result']
        assert res['pypi_whitelist'] == []
        assert res['mirror_whitelist'] == ['he-llo', 'django']
        mapp.set_mirror_whitelist("*")
        res = mapp.getjson("/cuser7/dev")['result']
        assert res['pypi_whitelist'] == []
        assert res['mirror_whitelist'] == ['*']


@pytest.mark.nomocking
class TestMirrorIndexThings:
    def test_create_and_delete_mirror_index(self, mapp, simpypi):
        mapp.create_and_login_user('mirror1')
        indexname = mapp.auth[0] + "/mirror"
        assert indexname not in mapp.getindexlist()
        indexconfig = dict(
            type="mirror",
            mirror_url=simpypi.simpleurl,
            mirror_cache_expiry=0)
        mapp.create_index("mirror", indexconfig=indexconfig)
        assert indexname in mapp.getindexlist()
        result = mapp.getjson('/mirror1/mirror')
        assert result['result']['mirror_url'] == simpypi.simpleurl
        assert result['result']['mirror_cache_expiry'] == 0
        mapp.delete_index("mirror")
        assert indexname not in mapp.getindexlist()

    def test_missing_package(self, mapp, simpypi):
        mapp.create_and_login_user('mirror2')
        indexconfig = dict(
            type="mirror",
            mirror_url=simpypi.simpleurl,
            mirror_cache_expiry=0)
        mapp.create_index("mirror", indexconfig=indexconfig)
        mapp.use("mirror2/mirror")
        result = mapp.getpkglist()
        assert result == []

    def test_no_releases(self, mapp, simpypi):
        mapp.create_and_login_user('mirror3')
        indexconfig = dict(
            type="mirror",
            mirror_url=simpypi.simpleurl,
            mirror_cache_expiry=0)
        mapp.create_index("mirror", indexconfig=indexconfig)
        mapp.use("mirror3/mirror")
        simpypi.add_project('pkg')
        result = mapp.getreleaseslist("pkg")
        assert result == []

    def test_releases(self, mapp, simpypi):
        mapp.create_and_login_user('mirror4')
        indexconfig = dict(
            type="mirror",
            mirror_url=simpypi.simpleurl,
            mirror_cache_expiry=0)
        mapp.create_index("mirror", indexconfig=indexconfig)
        mapp.use("mirror4/mirror")
        simpypi.add_release('pkg', pkgver='pkg-1.0.zip')
        result = mapp.getreleaseslist("pkg")
        base = simpypi.baseurl.replace('http://', 'http_').replace(':', '_')
        assert len(result) == 1
        assert result[0].endswith('/mirror4/mirror/+e/%s_pkg/pkg-1.0.zip' % base)

    def test_download_release_error(self, mapp, simpypi):
        mapp.create_and_login_user('mirror5')
        indexconfig = dict(
            type="mirror",
            mirror_url=simpypi.simpleurl,
            mirror_cache_expiry=0)
        mapp.create_index("mirror", indexconfig=indexconfig)
        mapp.use("mirror5/mirror")
        simpypi.add_release('pkg', pkgver='pkg-1.0.zip')
        result = mapp.getreleaseslist("pkg")
        assert len(result) == 1
        r = mapp.downloadrelease(502, result[0])
        msg = r['message']
        assert 'error 404 getting' in msg or 'received 502 from master' in msg

    def test_download_release(self, mapp, simpypi):
        mapp.create_and_login_user('mirror6')
        indexconfig = dict(
            type="mirror",
            mirror_url=simpypi.simpleurl,
            mirror_cache_expiry=0)
        mapp.create_index("mirror", indexconfig=indexconfig)
        mapp.use("mirror6/mirror")
        content = b'13'
        simpypi.add_release('pkg', pkgver='pkg-1.0.zip')
        simpypi.add_file('/pkg/pkg-1.0.zip', content)
        result = mapp.getreleaseslist("pkg")
        assert len(result) == 1
        r = mapp.downloadrelease(200, result[0])
        assert r == content

    def test_deleted_package(self, mapp, simpypi):
        mapp.create_and_login_user('mirror7')
        indexconfig = dict(
            type="mirror",
            mirror_url=simpypi.simpleurl,
            mirror_cache_expiry=1800)
        mapp.create_index("mirror", indexconfig=indexconfig)
        mapp.use("mirror7/mirror")
        simpypi.add_project('pkg')
        simpypi.add_release('pkg', pkgver='pkg-1.0.zip')
        result = mapp.getreleaseslist("pkg")
        assert len(result) == 1
        simpypi.remove_project('pkg')
        indexconfig['mirror_cache_expiry'] = 0
        mapp.modify_index("mirror7/mirror", indexconfig=indexconfig)
        result = mapp.getreleaseslist("pkg")
        # serving stale links indefinitely
        # we can't explicitly test for that here, because these tests also run
        # with devpi-client where we can't easily check the server output
        # XXX maybe we can add a function which parses the log on devpi-client
        # and the output in devpi-server?
        assert len(result) == 1

    def test_whitelisted_package_not_in_mirror(self, mapp, simpypi):
        if not hasattr(mapp, "get_simple"):
            # happens in the devpi-client tests
            pytest.skip("Mapp implementation doesn't have 'get_simple' method.")
        mapp.create_and_login_user('mirror8')
        indexconfig = dict(
            type="mirror",
            mirror_url=simpypi.simpleurl,
            mirror_cache_expiry=1800)
        mapp.create_index("mirror", indexconfig=indexconfig)
        indexconfig = dict(
            mirror_whitelist="*",
            bases="mirror8/mirror")
        mapp.create_index("regular", indexconfig=indexconfig)
        mapp.use("mirror8/regular")
        content = mapp.makepkg("pkg-1.0.tar.gz", b"content", "pkg", "1.0")
        mapp.upload_file_pypi("pkg-1.0.tar.gz", content, "pkg", "1.0")
        r = mapp.get_simple("pkg")
        assert b'ed7/002b439e9ac84/pkg-1.0.tar.gz' in r.body
