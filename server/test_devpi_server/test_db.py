
import py
import os
import pytest

@pytest.fixture(params=[(), ("root/pypi",)])
def bases(request):
    return request.param

def test_create_zipfile(tmpdir):
    content = create_zipfile({"one": {"nested": "1"}, "two": {}})
    tmpdir.join("hello.zip").write(content, "wb")

class TestStage:
    @pytest.fixture
    def stage(self, request, db):
        config = dict(user="hello", index="world", bases=(),
                      type="stage", volatile=True)
        if "bases" in request.fixturenames:
            config["bases"] = request.getfuncargvalue("bases")
        db.user_indexconfig_set(**config)
        return db.getstage(user=config["user"], index=config["index"])

    def test_create_and_delete(self, db):
        db.user_indexconfig_set(user="hello", index="world", bases=(),
                                type="stage", volatile=False)
        db.user_indexconfig_set(user="hello", index="world2", bases=(),
                                type="stage", volatile=False)
        db.user_indexconfig_delete(user="hello", index="world2")
        assert not db.user_indexconfig_get(user="hello", index="world2")
        assert db.user_indexconfig_get(user="hello", index="world")

    def test_set_and_get_acl(self, db):
        db.user_indexconfig_set(user="hello", index="world", bases=(),
                                type="stage", volatile=False,
                                acl_upload=["root"])
        indexconfig = db.user_indexconfig_get(user="hello", index="world")
        assert indexconfig["acl_upload"] == ["root"]
        stage = db.getstage("hello/world")
        assert stage.can_upload("root")
        assert not stage.can_upload("qweqwe")

    def test_not_configured_index(self, db):
        stagename = "hello/world"
        assert not db.getindexconfig(stagename)
        assert not db.getstage(stagename)

    def test_empty(self, stage, bases):
        assert not stage.getreleaselinks("someproject")
        assert not stage.getprojectnames()

    def test_inheritance_simple(self, httpget, stage):
        stage.configure(bases=("root/pypi",))
        httpget.setextsimple("someproject",
            "<a href='someproject-1.0.zip' /a>")
        entries = stage.getreleaselinks("someproject")
        assert len(entries) == 1
        assert stage.getprojectnames() == ["someproject",]
        stage.register_metadata(dict(name="someproject", version="1.1"))
        assert stage.getprojectnames() == ["someproject",]

    def test_inheritance_error(self, httpget, stage):
        stage.configure(bases=("root/pypi",))
        httpget.setextsimple("someproject", status_code = -1)
        entries = stage.getreleaselinks("someproject")
        assert entries == -1
        #entries = stage.getprojectnames()
        #assert entries == -1

    def test_get_projectconfig_inherited(self, httpget, stage):
        stage.configure(bases=("root/pypi",))
        httpget.setextsimple("someproject",
            "<a href='someproject-1.0.zip' /a>")
        projectconfig = stage.get_projectconfig("someproject")
        assert "someproject-1.0.zip" in projectconfig["1.0"]["+files"]

    def test_store_and_get_releasefile(self, stage, bases):
        content = "123"
        content2 = "1234"
        entry = stage.store_releasefile("some-1.0.zip", content)
        entries = stage.getreleaselinks("some")
        assert len(entries) == 1
        assert entries[0].md5 == entry.md5
        assert stage.getprojectnames() == ["some"]
        pconfig = stage.get_projectconfig("some")
        assert pconfig["1.0"]["+files"]["some-1.0.zip"].endswith("some-1.0.zip")

    def test_project_config_shadowed(self, httpget, stage):
        stage.configure(bases=("root/pypi",))
        httpget.setextsimple("someproject",
            "<a href='someproject-1.0.zip' /a>")
        content = "123"
        entry = stage.store_releasefile("someproject-1.0.zip", content)
        projectconfig = stage.get_projectconfig("someproject")
        files = projectconfig["1.0"]["+files"]
        link = files.values()[0]
        assert link.endswith("someproject-1.0.zip")
        assert projectconfig["1.0"]["+shadowing"]

    def test_store_and_delete_project(self, stage, bases):
        content = "123"
        entry = stage.store_releasefile("some-1.0.zip", content)
        pconfig = stage.get_projectconfig_perstage("some")
        assert pconfig["1.0"]
        stage.project_delete("some")
        pconfig = stage.get_projectconfig_perstage("some")
        assert not pconfig

    def test_store_and_delete_release(self, stage, bases):
        content = "123"
        entry = stage.store_releasefile("some-1.0.zip", content)
        entry = stage.store_releasefile("some-1.1.zip", content)
        pconfig = stage.get_projectconfig_perstage("some")
        assert pconfig["1.0"] and pconfig["1.1"]
        stage.project_version_delete("some", "1.0")
        pconfig = stage.get_projectconfig_perstage("some")
        assert pconfig["1.1"] and "1.0" not in pconfig
        stage.project_version_delete("some", "1.1")
        assert not stage.project_exists("some")

    def test_releasefile_sorting(self, stage, bases):
        content = "123"
        entry = stage.store_releasefile("some-1.1.zip", content)
        entry = stage.store_releasefile("some-1.0.zip", content)
        entries = stage.getreleaselinks("some")
        assert len(entries) == 2
        assert entries[0].basename == "some-1.1.zip"

    def test_storedoczipfile(self, stage, bases):
        content = create_zipfile({"index.html": "<html/>",
            "_static": {}, "_templ": {"x.css": ""}})
        filepath = stage.store_doczip("pkg1", content)
        assert filepath.join("index.html").check()
        assert filepath.join("_static").check(dir=1)
        assert filepath.join("_templ", "x.css").check(file=1)

    def test_storedoczipfile(self, stage, bases):
        content = create_zipfile({"index.html": "<html/>",
            "_static": {}, "_templ": {"x.css": ""}})
        filepath = stage.store_doczip("pkg1", content)
        content = create_zipfile({"nothing": "hello"})
        filepath = stage.store_doczip("pkg1", content)
        assert filepath.join("nothing").check()
        assert not filepath.join("index.html").check()
        assert not filepath.join("_static").check()
        assert not filepath.join("_templ").check()

    def test_store_and_get_volatile(self, stage):
        stage.configure(volatile=False)
        content = "123"
        content2 = "1234"
        entry = stage.store_releasefile("some-1.0.zip", content)
        assert len(stage.getreleaselinks("some")) == 1

        # rewrite  fails
        entry = stage.store_releasefile("some-1.0.zip", content2)
        assert entry == 409

        # rewrite succeeds with volatile
        stage.configure(volatile=True)
        entry = stage.store_releasefile("some-1.0.zip", content2)
        entries = stage.getreleaselinks("some")
        assert len(entries) == 1
        assert entries[0].FILE.get() == content2

    def test_releasedata(self, stage):
        assert stage.metadata_keys
        assert not stage.get_metadata("hello", "1.0")
        stage.register_metadata(dict(name="hello", version="1.0", author="xy"))
        d = stage.get_metadata("hello", "1.0")
        assert d["author"] == "xy"
        #stage.ixconfig["volatile"] = False
        #with pytest.raises(stage.MetadataExists):
        #    stage.register_metadata(dict(name="hello", version="1.0"))

    def test_releasedata_description(self, stage):
        source = py.std.textwrap.dedent("""\
            test the *world*
        """)
        assert stage.metadata_keys
        assert not stage.get_description("hello", "1.0")
        stage.register_metadata(dict(name="hello", version="1.0",
            description=source))
        html = stage.get_description("hello", "1.0")
        assert html
        assert "test" in html and "world" in html

    def test_releasedata_description_versions(self, stage):
        stage.register_metadata(dict(name="hello", version="1.0",
            description="hello"))
        stage.register_metadata(dict(name="hello", version="1.1",
            description="hello"))
        ver = stage.get_description_versions("hello")
        assert set(ver) == set(["1.0", "1.1"])


class TestUsers:
    def test_create_and_validate(self, db):
        assert not db.user_exists("user")
        db.user_create("user", "password", email="some@email.com")
        assert db.user_exists("user")
        userconfig = db.user_get("user")
        assert userconfig["email"] == "some@email.com"
        assert not set(userconfig).intersection(["pwsalt", "pwhash"])
        userconfig = db.user_get("user")
        assert db.user_validate("user", "password")
        assert not db.user_validate("user", "password2")

    def test_create_and_delete(self, db):
        db.user_setpassword("user", "password")
        db.user_delete("user")
        assert not db.user_exists("user")
        assert not db.user_validate("user", "password")

    def test_create_and_list(self, db):
        baselist = db.user_list()
        db.user_setpassword("user1", "password")
        db.user_setpassword("user2", "password")
        db.user_setpassword("user3", "password")
        newusers = db.user_list().difference(baselist)
        assert newusers == set("user1 user2 user3".split())
        db.user_delete("user3")
        newusers = db.user_list().difference(baselist)
        assert newusers == set("user1 user2".split())

    def test_server_passwd(self, db, monkeypatch):
        from devpi_server.db import run_passwd
        monkeypatch.setattr(py.std.getpass, "getpass", lambda x: "123")
        run_passwd(db, "root")
        assert db.user_validate("root", "123")

def test_setdefault_indexes(db):
    from devpi_server.main import set_default_indexes
    set_default_indexes(db)
    ixconfig = db.getindexconfig("root/pypi")
    assert ixconfig["type"] == "mirror"

    ixconfig = db.getindexconfig("root/dev")
    assert ixconfig["type"] == "stage"
    assert ixconfig["bases"] == ("root/pypi",)
    assert ixconfig["volatile"]


def create_zipfile(contentdict):
    f = py.io.BytesIO()
    zip = py.std.zipfile.ZipFile(f, "w")
    _writezip(zip, contentdict)
    zip.close()
    return f.getvalue()

def _writezip(zip, contentdict, prefixes=()):
    for name, val in contentdict.items():
        if isinstance(val, dict):
            newprefixes = prefixes + (name,)
            if not val:
                path = os.sep.join(newprefixes) + "/"
                zipinfo = py.std.zipfile.ZipInfo(path)
                zip.writestr(zipinfo, "")
            else:
                _writezip(zip, val, newprefixes)
        else:
            path = os.sep.join(prefixes + (name,))
            zip.writestr(path, val)


