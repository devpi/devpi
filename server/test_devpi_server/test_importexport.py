from __future__ import unicode_literals

import sys
import pytest
import subprocess
from devpi_server.importexport import *
from devpi_server.main import Fatal
from devpi_common.archive import zip_dict

import devpi_server

def test_not_exists(tmpdir, xom):
    p = tmpdir.join("hello")
    with pytest.raises(Fatal):
         do_import(p, xom)

def test_import_wrong_dumpversion(tmpdir, xom):
    tmpdir.join("dataindex.json").write('{"dumpversion": "0"}')
    with pytest.raises(Fatal):
        do_import(tmpdir, xom)

def test_empty_export(tmpdir, xom):
    ret = do_export(tmpdir, xom)
    assert not ret
    data = json.loads(tmpdir.join("dataindex.json").read())
    assert data["dumpversion"] == Exporter.DUMPVERSION
    assert data["pythonversion"] == list(sys.version_info)
    assert data["devpi_server"] == devpi_server.__version__
    with pytest.raises(Fatal):
        do_export(tmpdir, xom)

def test_import_on_existing_server_data(tmpdir, xom):
    xom.db.user_create("someuser", "qwe")
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


class TestImportExport:
    @pytest.fixture
    def impexp(self, makemapp, gentmp):
        class ImpExp:
            def __init__(self):
                self.exportdir = gentmp()
                self.mapp1 = makemapp(options=[
                    "--export", self.exportdir]
                )

            def export(self):
                assert self.mapp1.xom.main() == 0

            def new_import(self):
                mapp2 = makemapp(options=("--import", str(self.exportdir)))
                assert mapp2.xom.main() == 0
                return mapp2
        return ImpExp()

    def test_two_indexes_inheriting(self, impexp):
        mapp1 = impexp.mapp1
        api = mapp1.create_and_use()
        stagename2 = api.user + "/" + "dev6"
        mapp1.create_index(stagename2, indexconfig=dict(bases=api.stagename))
        impexp.export()
        mapp2 = impexp.new_import()
        assert api.user in mapp2.getuserlist()
        indexlist = mapp2.getindexlist(api.user)
        assert indexlist[stagename2]["bases"] == [api.stagename]
        assert stagename2 in indexlist
        assert mapp2.xom.config.secret == mapp1.xom.config.secret

    def test_upload_releasefile_with_attachment(self, impexp):
        mapp1 = impexp.mapp1
        api = mapp1.create_and_use()
        mapp1.upload_file_pypi("hello-1.0.tar.gz", b"content",
                               "hello", "1.0")

        md5 = py.std.hashlib.md5(b"content").hexdigest()
        num = mapp1.xom.filestore.add_attachment(
                    md5=md5, type="toxresult", data="123")
        impexp.export()
        mapp2 = impexp.new_import()
        stage = mapp2.xom.db.getstage(api.stagename)
        entries = stage.getreleaselinks("hello")
        assert len(entries) == 1
        assert entries[0].FILE.get() == b"content"
        x = mapp2.xom.filestore.get_attachment(
            md5=md5, type="toxresult", num=num)
        assert x == "123"

    def test_user_no_index_login_works(self, impexp):
        mapp1 = impexp.mapp1
        mapp1.create_and_login_user("exp", "pass")
        impexp.export()
        mapp2 = impexp.new_import()
        mapp2.login("exp", "pass")

    def test_docs_are_preserved(self, impexp):
        mapp1 = impexp.mapp1
        api = mapp1.create_and_use()
        mapp1.register_metadata({"name": "hello", "version": "1.0"})
        content = zip_dict({"index.html": "<html/>"})
        mapp1.upload_doc("hello.zip", content, "hello", "")
        impexp.export()
        mapp2 = impexp.new_import()
        stage = mapp2.xom.db.getstage(api.stagename)
        path = stage._doc_key("hello", "1.0").filepath
        assert path.check()
        assert path.join("index.html").read() == "<html/>"

    def test_10_upload_docs_no_version(self, impexp):
        mapp1 = impexp.mapp1
        api = mapp1.create_and_use()
        # in devpi-server 1.0 one could upload a doc
        # without ever registering the project, leading to empty
        # versions.  We simulate it here because 1.1 http API
        # prevents this case.
        stage = mapp1.xom.db.getstage(api.stagename)
        stage._register_metadata({"name": "hello", "version": ""})
        impexp.export()
        mapp2 = impexp.new_import()
        stage = mapp2.xom.db.getstage(api.stagename)
        assert not stage.get_project_info("hello")

    def test_10_normalized_projectnames(self, impexp):
        mapp1 = impexp.mapp1
        api = mapp1.create_and_use()
        # in devpi-server 1.0 one could register X_Y and X-Y names
        # and they would get registeded under different names.
        # We simulate it here because 1.1 http API prevents this case.
        stage = mapp1.xom.db.getstage(api.stagename)
        stage._register_metadata({"name": "hello_x", "version": "1.0"})
        stage._register_metadata({"name": "hello-X", "version": "1.1"})
        stage._register_metadata({"name": "Hello-X", "version": "1.2"})
        impexp.export()
        mapp2 = impexp.new_import()
        stage = mapp2.xom.db.getstage(api.stagename)
        def n(name):
            return stage.get_project_info(name).name
        assert n("hello-x") == "Hello-X"
        assert n("Hello_x") == "Hello-X"
        config = stage.get_projectconfig("Hello-X")
        assert len(config) == 3
        assert config["1.0"]["name"] == "Hello-X"
        assert config["1.0"]["version"] == "1.0"
        assert config["1.1"]["name"] == "Hello-X"
        assert config["1.2"]["name"] == "Hello-X"

    def test_10_no_empty_releases(self, impexp):
        mapp1 = impexp.mapp1
        api = mapp1.create_and_use()
        # in devpi-server 1.0 one could register X_Y and X-Y names
        # and they would get registeded under different names.
        # We simulate it here because 1.1 http API prevents this case.
        stage = mapp1.xom.db.getstage(api.stagename)
        stage._register_metadata({"name": "hello_x", "version": "1.0"})
        stage._register_metadata({"name": "hello_x", "version": ""})
        impexp.export()
        mapp2 = impexp.new_import()
        stage = mapp2.xom.db.getstage(api.stagename)
        projconfig = stage.get_projectconfig("hello_x")
        assert list(projconfig) == ["1.0"]


    def test_10_normalized_projectnames_with_inheritance(self, impexp):
        mapp1 = impexp.mapp1
        api = mapp1.create_and_use()
        # in devpi-server 1.0 one could register X_Y and X-Y names
        # and they would get registeded under different names.
        # We simulate it here because 1.1 http API prevents this case.
        stage = mapp1.xom.db.getstage(api.stagename)
        stage._register_metadata({"name": "hello_x", "version": "1.0"})
        stage._register_metadata({"name": "hello-X", "version": "1.1"})
        api2 = mapp1.create_index("new2", indexconfig={"bases": api.stagename})
        stage2 = mapp1.xom.db.getstage(api2.stagename)
        stage2._register_metadata({"name": "hello_X", "version": "0.9"})
        impexp.export()
        mapp2 = impexp.new_import()
        stage2 = mapp2.xom.db.getstage(api2.stagename)
        def n(name):
            return stage2.get_project_info(name).name
        assert n("hello-x") == "hello-X"
        assert n("Hello_x") == "hello-X"

    def test_10_pypi_names_precedence(self, impexp, monkeypatch):
        mapp1 = impexp.mapp1
        api = mapp1.create_and_use()
        # in devpi-server 1.0 one could register X_Y and X-Y names
        # and they would get registeded under different names.
        # We simulate it here because 1.1 http API prevents this case.
        stage = mapp1.xom.db.getstage(api.stagename)
        monkeypatch.setattr(mapp1.xom.extdb, "getprojectnames_perstage",
                            lambda: ["hello_X"])
        stage._register_metadata({"name": "hello_x", "version": "1.1"})
        stage._register_metadata({"name": "hello-X", "version": "1.0"})
        impexp.export()
        mapp2 = impexp.new_import()
        stage2 = mapp2.xom.db.getstage(api.stagename)
        def n(name):
            return stage2.get_project_info(name).name
        assert n("hello-x") == "hello_X"
        assert n("Hello_x") == "hello_X"


def test_upgrade(makexom, monkeypatch):
    def invoke_export(commands):
        assert "--serverdir" in commands
        assert "--export" in commands

    def invoke_import(commands):
        assert "--serverdir" in commands
        assert "--import" in commands

    def patch(commands):
        try:
            i = commands.index("--export")
        except ValueError:
            assert "--import" in commands
            i = commands.index("--serverdir")
            version = py.path.local(commands[i+1]).ensure(".serverversion")
            version.write(devpi_server.__version__)
        else:
            py.path.local(commands[i+1]).ensure(dir=1)

    monkeypatch.setattr(subprocess, "check_call", patch)
    xom = makexom(["--upgrade-state"])
    do_upgrade(xom)
    assert xom.config.serverdir.check()
    assert not (xom.config.serverdir + "-export").check()
    assert (xom.config.serverdir + "-backup").check()

