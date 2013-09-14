import pytest
from devpi_server.importexport import *
from devpi_server.main import main, Fatal


def test_not_exists(tmpdir, xom):
    p = tmpdir.join("hello")
    with pytest.raises(Fatal):
         do_import(p, xom)

def test_import_wrong_dumpversion(tmpdir, xom):
    tmpdir.join("dumpversion").write("1lk23j123")
    with pytest.raises(Fatal):
        do_import(tmpdir, xom)

def test_empty_export(tmpdir, xom):
    ret = do_export(tmpdir, xom)
    assert not ret
    assert tmpdir.join("dumpversion").read() == Exporter.DUMPVERSION

def test_import_on_existing_server_data(tmpdir, xom):
    assert not do_export(tmpdir, xom)
    with pytest.raises(Fatal):
        do_import(tmpdir, xom)

class TestIndexTree:
    def test_basic(self):
        tree = IndexTree()
        tree.add("name1", ["name2"])
        tree.add("name2", ["name3"])
        tree.add("name3", None)
        assert list(tree.iternames()) == ["name3", "name2", "name1"]

    def test_multi_inheritance(self):
        tree = IndexTree()
        tree.add("name1", ["name2", "name3"])
        tree.add("name2", ["name4"])
        tree.add("name3", [])
        tree.add("name4", [])
        names = list(tree.iternames())
        assert len(names) == 4
        assert names.index("name1") > names.index("name2")
        assert names.index("name2") > names.index("name4")
        assert names.index("name1") == 3

def test_import_default(tmpdir, xom):
    assert not do_export(tmpdir, xom)
    new = tmpdir.join("new")
    main(["devpi-server", "--import", str(tmpdir),
          "--serverdir", str(new)])
    assert xom.config.secret == new.join(".secret").read()

class TestImportExport:
    @pytest.fixture
    def xom_dest(self, tmpdir):
        from devpi_server.main import parseoptions, XOM
        destdir = tmpdir.join("destdir")
        assert not destdir.check()
        config = parseoptions(
            ["devpi-server", "--import", "x", "--serverdir", str(destdir)])
        return XOM(config)

    @pytest.fixture
    def impexp(self, makemapp, gentmp):
        class ImpExp:
            def __init__(self):
                self.mapp1 = makemapp()
                self.exportdir = gentmp()

            def export(self):
                assert do_export(self.exportdir, self.mapp1.xom) == 0

            def new_import(self):
                mapp2 = makemapp(options=("--import", str(self.exportdir)))
                assert do_import(self.exportdir, mapp2.xom) == 0
                return mapp2

        return ImpExp()

    def test_two_indexes_inheriting(self, impexp):
        mapp1 = impexp.mapp1
        mapp1.create_and_login_user("exp")
        mapp1.create_index("dev5")
        mapp1.create_index("dev6", indexconfig=dict(bases="exp/dev5"))
        impexp.export()
        mapp2 = impexp.new_import()
        assert "exp" in mapp2.getuserlist()
        indexlist = mapp2.getindexlist("exp")
        assert indexlist["exp/dev6"]["bases"] == ["exp/dev5"]
        assert "exp/dev6" in indexlist

    def test_upload_releasefile_with_attachment(self, impexp):
        mapp1 = impexp.mapp1
        mapp1.create_and_login_user("exp")
        mapp1.create_index("dev5")
        mapp1.use("exp/dev5")
        mapp1.upload_file_pypi("hello-1.0.tar.gz", "content",
                     "hello", "1.0")

        md5 = py.std.md5.md5("content").hexdigest()
        num = mapp1.xom.releasefilestore.add_attachment(
                    md5=md5, type="toxresult", data="123")
        impexp.export()
        mapp2 = impexp.new_import()
        stage = mapp2.xom.db.getstage("exp/dev5")
        entries = stage.getreleaselinks("hello")
        assert len(entries) == 1
        assert entries[0].FILE.get() == "content"
        x = mapp2.xom.releasefilestore.get_attachment(
            md5=md5, type="toxresult", num=num)
        assert x == "123"

    def test_user_no_index_login_works(self, impexp):
        mapp1 = impexp.mapp1
        mapp1.create_and_login_user("exp", "pass")
        impexp.export()
        mapp2 = impexp.new_import()
        mapp2.login("exp", "pass")

