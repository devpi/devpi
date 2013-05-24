
import pytest

@pytest.fixture(params=[(), ("ext/pypi",)])
def bases(request):
    return request.param


class TestStage:
    @pytest.fixture
    def stage(self, request, db):
        config = dict(user="hello", index="world", bases=(),
                      type="private", volatile=True)
        if "bases" in request.fixturenames:
            config["bases"] = request.getfuncargvalue("bases")
        db.user_indexconfig_set(**config)
        return db.getstage(user=config["user"], index=config["index"])

    def test_not_configured_index(self, db):
        stagename = "hello/world"
        assert not db.getindexconfig(stagename)
        assert not db.getstage(stagename)

    def test_empty(self, stage, bases):
        assert not stage.getreleaselinks("someproject")
        assert not stage.getprojectnames()

    def test_inheritance_simple(self, httpget, stage):
        stage.configure(bases=("ext/pypi",))
        httpget.setextsimple("someproject",
            "<a href='someproject-1.0.zip' /a>")
        entries = stage.getreleaselinks("someproject")
        assert len(entries) == 1
        assert stage.getprojectnames() == ["someproject",]

    def test_inheritance_error(self, httpget, stage):
        stage.configure(bases=("ext/pypi",))
        httpget.setextsimple("someproject", status_code = -1)
        entries = stage.getreleaselinks("someproject")
        assert entries == -1
        #entries = stage.getprojectnames()
        #assert entries == -1

    def test_store_and_get_releasefile(self, stage, bases):
        content = "123"
        content2 = "1234"
        entry = stage.store_releasefile("some-1.0.zip", content)
        entries = stage.getreleaselinks("some")
        assert len(entries) == 1
        assert entries[0].md5 == entry.md5
        assert stage.getprojectnames() == ["some"]

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

class TestUsers:
    def test_create_and_validate(self, db):
        assert not db.user_exists("user")
        db.user_setpassword("user", "password")
        assert db.user_exists("user")
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

def test_setdefault_indexes(db):
    from devpi_server.main import set_default_indexes
    set_default_indexes(db)
    ixconfig = db.getindexconfig("ext/pypi")
    assert ixconfig["type"] == "pypimirror"

    ixconfig = db.getindexconfig("int/dev")
    assert ixconfig["type"] == "private"
    assert ixconfig["bases"] == ("int/prod", "ext/pypi")
    assert ixconfig["volatile"]

    ixconfig = db.getindexconfig("int/prod")
    assert ixconfig["type"] == "private"
    assert ixconfig["bases"] == ()
    assert not ixconfig["volatile"]
