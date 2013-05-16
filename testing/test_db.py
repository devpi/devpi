
import pytest


def test_bases(db):
    db.setbases("somestage", "somebase")
    assert db.getbases("somestage") == ("somebase",)
    db.setbases("somestage", "base1,base2")
    assert db.getbases("somestage") == ("base1", "base2")

class TestDB:
    @pytest.mark.parametrize("bases", ["", "ext/pypi"])
    def test_empty(self, redis, db, bases):
        stagename = "hello/world"
        assert not db.getreleaselinks(stagename, "someproject")
        db.setbases(stagename, bases)
        assert not db.getreleaselinks(stagename, "someproject")
        assert not db.getprojectnames(stagename)

    @pytest.mark.parametrize("bases", ["", "ext/pypi"])
    def test_releaselinks(self, redis, db, bases):
        stagename = "hello/world"
        db.setbases(stagename, bases)
        entries = db.getreleaselinks(stagename, "someproject")
        assert not entries
        entries = db.getprojectnames(stagename)
        assert not entries

    def test_inheritance_simple(self, redis, httpget, db):
        stagename = "hello/world"
        db.setbases(stagename, "ext/pypi")
        httpget.setextsimple("someproject",
            "<a href='someproject-1.0.zip' /a>")
        entries = db.getreleaselinks(stagename, "someproject")
        assert len(entries) == 1
        assert db.getprojectnames(stagename) == ["someproject",]

    def test_inheritance_error(self, redis, httpget, db):
        stagename = "hello/world"
        db.setbases(stagename, "ext/pypi")
        httpget.setextsimple("someproject", status_code = -1)
        entries = db.getreleaselinks(stagename, "someproject")
        assert entries == -1
        #entries = db.getprojectnames(stagename)
        #assert entries == -1

    def test_store_and_get_releasefile(self, db):
        stagename = "test/dev"
        content = "123"
        entry = db.store_releasefile(stagename, "some-1.0.zip", content)
        entries = db.getreleaselinks(stagename, "some")
        assert len(entries) == 1
        assert entries[0].md5 == entry.md5
