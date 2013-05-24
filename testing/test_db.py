
import pytest


class TestDB:

    def test_configure_index(self, db):
        stagename = "hello/world"
        ixconfig = db.getindexconfig(stagename)
        assert not ixconfig
        db.configure_index(stagename, bases=("int/dev",))
        ixconfig = db.getindexconfig(stagename)
        assert ixconfig["type"] == "private"
        assert ixconfig["bases"] == ("int/dev",)

    @pytest.mark.parametrize("bases", ["", "ext/pypi"])
    def test_empty(self, db, bases):
        stagename = "hello/world"
        assert db.getreleaselinks(stagename, "someproject") == 404
        db.configure_index(stagename, bases=bases)
        assert not db.getreleaselinks(stagename, "someproject")
        assert not db.getprojectnames(stagename)

    @pytest.mark.parametrize("bases", ["", "ext/pypi"])
    def test_releaselinks(self, db, bases):
        stagename = "hello/world"
        db.configure_index(stagename, bases=bases)
        entries = db.getreleaselinks(stagename, "someproject")
        assert not entries
        entries = db.getprojectnames(stagename)
        assert not entries

    def test_inheritance_simple(self, httpget, db):
        stagename = "hello/world"
        db.configure_index(stagename, bases=("ext/pypi",))
        httpget.setextsimple("someproject",
            "<a href='someproject-1.0.zip' /a>")
        entries = db.getreleaselinks(stagename, "someproject")
        assert len(entries) == 1
        assert db.getprojectnames(stagename) == ["someproject",]

    def test_inheritance_error(self, httpget, db):
        stagename = "hello/world"
        db.configure_index(stagename, bases=("ext/pypi",))
        httpget.setextsimple("someproject", status_code = -1)
        entries = db.getreleaselinks(stagename, "someproject")
        assert entries == -1
        #entries = db.getprojectnames(stagename)
        #assert entries == -1

    def test_store_and_get_releasefile(self, db):
        stagename = "test/dev"
        db.configure_index(stagename)
        content = "123"
        content2 = "1234"
        entry = db.store_releasefile(stagename, "some-1.0.zip", content)
        entries = db.getreleaselinks(stagename, "some")
        assert len(entries) == 1
        assert entries[0].md5 == entry.md5

    def test_store_and_get_volatile(self, db):
        stagename = "test/dev"
        db.configure_index(stagename, volatile=False)
        content = "123"
        content2 = "1234"
        entry = db.store_releasefile(stagename, "some-1.0.zip", content)
        entries = db.getreleaselinks(stagename, "some")
        assert len(entries) == 1

        # rewrite  fails
        entry = db.store_releasefile(stagename, "some-1.0.zip", content2)
        assert entry == 409

        # rewrite succeeds with volatile
        db.configure_index(stagename, volatile=True)
        entry = db.store_releasefile(stagename, "some-1.0.zip", content2)
        entries = db.getreleaselinks(stagename, "some")
        assert len(entries) == 1
        assert entries[0].FILE.get() == content2

class TestUsers:
    def test_create_and_validate(self, db):
        assert not db.user_exists("user")
        db.user_create("user", "password")
        assert db.user_exists("user")
        assert db.user_validate("user", "password")
        assert not db.user_validate("user", "password2")

    def test_create_and_delete(self, db):
        db.user_create("user", "password")
        db.user_delete("user")
        assert not db.user_exists("user")
        assert not db.user_validate("user", "password")

    def test_create_and_list(self, db):
        db.user_create("user1", "password")
        db.user_create("user2", "password")
        db.user_create("user3", "password")
        assert db.user_list() == set("user1 user2 user3".split())
        db.user_delete("user3")
        assert db.user_list() == set("user1 user2".split())

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
