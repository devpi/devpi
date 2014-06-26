from __future__ import unicode_literals

import sys
import pytest
import subprocess
from devpi_server.importexport import *
from devpi_server.main import Fatal
from devpi_common.archive import zip_dict

import devpi_server

pytestmark = [pytest.mark.notransaction]

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
    with xom.keyfs.transaction(write=True):
        xom.model.create_user("someuser", password="qwe")
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
        assert stagename2 in indexlist
        assert indexlist[stagename2]["bases"] == [api.stagename]
        assert mapp2.xom.config.secret == mapp1.xom.config.secret

    def test_upload_releasefile_with_toxresult(self, impexp):
        from test_devpi_server.example import tox_result_data
        mapp1 = impexp.mapp1
        api = mapp1.create_and_use()
        content = b'content'
        mapp1.upload_file_pypi("hello-1.0.tar.gz", content, "hello", "1.0")
        path, = mapp1.get_release_paths("hello")
        path = path.strip("/")
        with mapp1.xom.keyfs.transaction(write=True):
            stage = mapp1.xom.model.getstage(api.stagename)
            link = stage.get_link_from_entrypath(path)
            stage.store_toxresult(link, tox_result_data)
        impexp.export()
        mapp2 = impexp.new_import()
        with mapp2.xom.keyfs.transaction(write=False):
            stage = mapp2.xom.model.getstage(api.stagename)
            entries = stage.getreleaselinks("hello")
            assert len(entries) == 1
            assert entries[0].file_get_content() == b"content"
            link = stage.get_link_from_entrypath(entries[0].relpath)
            results = stage.get_toxresults(link)
            assert len(results) == 1
            assert results[0] == tox_result_data

    def test_user_no_index_login_works(self, impexp):
        mapp1 = impexp.mapp1
        mapp1.create_and_login_user("exp", "pass")
        impexp.export()
        mapp2 = impexp.new_import()
        mapp2.login("exp", "pass")

    def test_docs_are_preserved(self, impexp):
        from devpi_common.archive import Archive
        mapp1 = impexp.mapp1
        api = mapp1.create_and_use()
        mapp1.register_metadata({"name": "hello", "version": "1.0"})
        content = zip_dict({"index.html": "<html/>"})
        mapp1.upload_doc("hello.zip", content, "hello", "")
        impexp.export()
        mapp2 = impexp.new_import()
        with mapp2.xom.keyfs.transaction(write=False):
            stage = mapp2.xom.model.getstage(api.stagename)
            doczip = stage.get_doczip("hello", "1.0")
            archive = Archive(py.io.BytesIO(doczip))
            assert 'index.html' in archive.namelist()
            assert py.builtin._totext(
                archive.read("index.html"), 'utf-8') == "<html/>"

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

