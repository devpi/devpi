
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
        db.index_create(**config)
        return db.getstage(user=config["user"], index=config["index"])

    def test_create_and_delete(self, db):
        db.index_create(user="hello", index="world", bases=(),
                        type="stage", volatile=False)
        db.index_create(user="hello", index="world2", bases=(),
                        type="stage", volatile=False)
        db.index_delete(user="hello", index="world2")
        assert not db.index_get(user="hello", index="world2")
        assert db.index_get(user="hello", index="world")

    def test_set_and_get_acl(self, db):
        db.index_create(user="hello", index="world", bases=(),
                        type="stage", volatile=False)
        indexconfig = db.index_get(user="hello", index="world")
        # check that "hello" was included in acl_upload by default
        assert indexconfig["acl_upload"] == ["hello"]
        stage = db.getstage("hello/world")
        # root cannot upload
        assert not stage.can_upload("root")

        # and we remove 'hello' from acl_upload ...
        assert db.index_modify(user="hello", index="world", acl_upload=[])
        # ... it cannot upload either
        stage = db.getstage("hello/world")
        assert not stage.can_upload("hello")

    def test_getstage_normalized(self, db):
        assert db.getstage("/root/pypi/").name == "root/pypi"

    def test_not_configured_index(self, db):
        stagename = "hello/world"
        assert not db.index_get(stagename)
        assert not db.getstage(stagename)

    def test_indexconfig_set_throws_on_unknown_base_index(self, db):
        with pytest.raises(db.InvalidIndexconfig) as excinfo:
            db.index_create(user="hello", index="world",
                            bases=("root/notexists", "root/notexists2"),)
        messages = excinfo.value.messages
        assert len(messages) == 2
        assert "root/notexists" in messages[0]
        assert "root/notexists2" in messages[1]

    def test_indexconfig_set_throws_on_invalid_base_index(self, db):
        with pytest.raises(db.InvalidIndexconfig) as excinfo:
            db.index_create(user="hello", index="world",
                            bases=("root/dev/123",),)
        messages = excinfo.value.messages
        assert len(messages) == 1
        assert "root/dev/123" in messages[0]

    def test_indexconfig_set_normalizes_bases(self, db):
        ixconfig = db.index_create(user="hello", index="world",
                                   bases=("/root/pypi/",))
        assert ixconfig["bases"] == ("root/pypi",)

    def test_empty(self, stage, bases):
        assert not stage.getreleaselinks("someproject")
        assert not stage.getprojectnames()

    def test_inheritance_simple(self, httpget, stage, db):
        stage._reconfigure(bases=("root/pypi",))
        httpget.setextsimple("someproject",
            "<a href='someproject-1.0.zip' /a>")
        entries = stage.getreleaselinks("someproject")
        assert len(entries) == 1
        assert stage.getprojectnames() == ["someproject",]
        stage.register_metadata(dict(name="someproject", version="1.1"))
        assert stage.getprojectnames() == ["someproject",]

    def test_inheritance_twice(self, httpget, db, stage):
        db.index_create(user="root", index="dev2", bases=("root/pypi",))
        stage_dev2 = db.getstage("root/dev2")
        stage._reconfigure(bases=("root/dev2",))
        httpget.setextsimple("someproject",
            "<a href='someproject-1.0.zip' /a>")
        stage_dev2.store_releasefile("someproject-1.1.tar.gz", "123")
        stage.store_releasefile("someproject-1.2.tar.gz", "456")
        entries = stage.getreleaselinks("someproject")
        assert len(entries) == 3
        assert entries[0].basename == "someproject-1.2.tar.gz"
        assert entries[1].basename == "someproject-1.1.tar.gz"
        assert entries[2].basename == "someproject-1.0.zip"
        assert stage.getprojectnames() == ["someproject",]

    def test_inheritance_normalize_multipackage(self, httpget, db, stage):
        stage._reconfigure(bases=("root/pypi",))
        httpget.setextsimple("some-project", """
            <a href='some_project-1.0.zip' /a>
            <a href='some_project-1.0.tar.gz' /a>
        """)
        stage.store_releasefile("some_project-1.2.tar.gz", "456")
        entries = stage.getreleaselinks("some-project")
        assert len(entries) == 3
        assert entries[0].basename == "some_project-1.2.tar.gz"
        assert entries[1].basename == "some_project-1.0.zip"
        assert entries[2].basename == "some_project-1.0.tar.gz"
        assert stage.getprojectnames() == ["some-project",]

    def test_getreleaselinks_inheritance_shadow(self, httpget, stage):
        stage._reconfigure(bases=("root/pypi",))
        httpget.setextsimple("someproject",
            "<a href='someproject-1.0.zip' /a>")
        stage.store_releasefile("someproject-1.0.zip", "123")
        entries = stage.getreleaselinks("someproject")
        assert len(entries) == 1
        assert entries[0].relpath.endswith("someproject-1.0.zip")

    def test_getreleaselinks_inheritance_shadow_egg(self, httpget, stage):
        stage._reconfigure(bases=("root/pypi",))
        httpget.setextsimple("py",
        """<a href="http://bb.org/download/py.zip#egg=py-dev" />""")
        stage.store_releasefile("py-1.0.tar.gz", "123")
        entries = stage.getreleaselinks("py")
        assert len(entries) == 2
        e0, e1 = entries
        assert e0.basename == "py.zip"
        assert e1.basename == "py-1.0.tar.gz"

    def test_inheritance_error(self, httpget, stage):
        stage._reconfigure(bases=("root/pypi",))
        httpget.setextsimple("someproject", status_code = -1)
        entries = stage.getreleaselinks("someproject")
        assert entries == -1
        #entries = stage.getprojectnames()
        #assert entries == -1

    def test_get_projectconfig_inherited(self, httpget, stage):
        stage._reconfigure(bases=("root/pypi",))
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
        stage._reconfigure(bases=("root/pypi",))
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
        stage._reconfigure(volatile=False)
        content = "123"
        content2 = "1234"
        entry = stage.store_releasefile("some-1.0.zip", content)
        assert len(stage.getreleaselinks("some")) == 1

        # rewrite  fails
        entry = stage.store_releasefile("some-1.0.zip", content2)
        assert entry == 409

        # rewrite succeeds with volatile
        stage._reconfigure(volatile=True)
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
        db.user_create("user", password="password")
        assert db.user_exists("user")
        db.user_delete("user")
        assert not db.user_exists("user")
        assert not db.user_validate("user", "password")

    def test_create_and_list(self, db):
        baselist = db.user_list()
        db.user_modify("user1", password="password")
        db.user_modify("user2", password="password")
        db.user_modify("user3", password="password")
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

    def test_server_email(self, db):
        email_address = "root_" + str(id) + "@mydomain"
        db.user_modify('root', email=email_address)
        assert db.user_get("root")["email"] == email_address


def test_setdefault_indexes(db):
    from devpi_server.main import set_default_indexes
    set_default_indexes(db)
    ixconfig = db.index_get("root/pypi")
    assert ixconfig["type"] == "mirror"

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


