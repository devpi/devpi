from __future__ import unicode_literals

import sys
import pytest
import subprocess
import json
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

    def test_uuid(self, impexp):
        impexp.export()
        mapp2 = impexp.new_import()
        assert mapp2.xom.config.nodeinfo["uuid"] == \
              impexp.mapp1.xom.config.nodeinfo["uuid"]

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
            links = stage.get_releaselinks("hello")
            assert len(links) == 1
            assert links[0].entry.file_get_content() == b"content"
            link = stage.get_link_from_entrypath(links[0].entrypath)
            results = stage.get_toxresults(link)
            assert len(results) == 1
            assert results[0] == tox_result_data

    def test_version_not_set_in_imported_versiondata(self, impexp):
        mapp1 = impexp.mapp1
        api = mapp1.create_and_use()
        content = b'content'
        mapp1.upload_file_pypi("hello-1.0.tar.gz", content, "hello", "1.0")

        # simulate a data structure where "version" is missing
        with mapp1.xom.keyfs.transaction(write=True):
            stage = mapp1.xom.model.getstage(api.stagename)
            key_projversion = stage.key_projversion("hello", "1.0")
            verdata = key_projversion.get()
            del verdata["version"]
            key_projversion.set(verdata)
        impexp.export()

        # and check that it was derived while importing
        mapp2 = impexp.new_import()

        with mapp2.xom.keyfs.transaction():
            stage = mapp2.xom.model.getstage(api.stagename)
            verdata = stage.get_versiondata_perstage("hello", "1.0")
            assert verdata["version"] == "1.0"
            links = stage.get_releaselinks("hello")
            assert len(links) == 1
            assert links[0].entry.file_get_content() == b"content"

    def test_dashes_to_undescores_when_imported_from_v1(self, impexp):
        """ Much like the above case, but exported from a version 1.2 server,
            and the the version had a dash in the name which was stored
            on disk as an underscore. Eg:

              hello-1.2-3.tar.gz  ->  hello-1.2_3.tar.gz

            In this case the Registration entry won't match the inferred version
            data for the file.
        """
        mapp1 = impexp.mapp1
        api = mapp1.create_and_use()

        # This is the raw json of the data that shows up this issue.
        DUMP_FILE = {
          "dumpversion": "1",
          "secret": "qREGpVy0mj2auDp/z/7JpQe/as9XJQl3GZGW75SSH9U=",
          "pythonversion": list(sys.version_info),
          "devpi_server": "1.2",
          "indexes": {
              "user1/dev": {
                  "projects": {
                      "hello": {
                          "1.2-3": {
                              "author": "",
                              "home_page": "",
                              "version": "1.2-3",
                              "keywords": "",
                              "name": "hello",
                              "classifiers": [],
                              "download_url": "",
                              "author_email": "",
                              "license": "",
                              "platform": [],
                              "summary": "",
                              "description": "",
                           },
                      },
                  },
                  "files": [
                      {
                          "entrymapping": {
                            "last_modified": "Fri, 04 Jul 2014 14:40:13 GMT",
                            "md5": "9a0364b9e99bb480dd25e1f0284c8555",
                            "size": "7"
                          },
                          "projectname": "hello",
                          "type": "releasefile",
                          "relpath": "user1/dev/hello/hello-1.2_3.tar.gz"
                      },
                  ],
                  "indexconfig": {
                      "uploadtrigger_jenkins": None,
                      "volatile": True,
                      "bases": [
                          "root/pypi"
                      ],
                      "acl_upload": [
                          "user1"
                      ],
                      "type": "stage"
                  },
              },
          },
          "users": {
              "root": {
                "pwhash": "265ed9fb83bef361764838b7099e9627570016629db4e8e1b930817b1a4793af",
                "username": "root",
                "pwsalt": "A/4FsRp5oTkovbtTfhlx1g=="
              },
              "user1": {
                  "username": "user1",
                  "pwsalt": "RMAM7ycp8aqw4vytBOBEKA==",
                  "pwhash": "d9f98f41f8cbdeb6a30a7b6c376d0ccdd76e862ad1fa508b79d4c2098cc9d69a"
             }
          }
        }
        with open(impexp.exportdir.join('dataindex.json').strpath, 'w') as fp:
            fp.write(json.dumps(DUMP_FILE))

        filedir = impexp.exportdir
        for dir in ['user1', 'dev', 'hello']:
            filedir = filedir.join(dir)
            filedir.mkdir()
        with open(filedir.join('hello-1.2_3.tar.gz').strpath, 'w') as fp:
            fp.write('content')

        # Run the import and check the version data
        mapp2 = impexp.new_import()
        with mapp2.xom.keyfs.transaction():
            stage = mapp2.xom.model.getstage(api.stagename)
            verdata = stage.get_versiondata_perstage("hello", "1.2-3")
            assert verdata["version"] == "1.2-3"

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
        mapp1.set_versiondata({"name": "hello", "version": "1.0"})
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

    def test_name_mangling_relates_to_issue132(self, impexp):
        mapp1 = impexp.mapp1
        api = mapp1.create_and_use()
        content = b'content'
        mapp1.upload_file_pypi("he-llo-1.0.tar.gz", content, "he_llo", "1.0")
        mapp1.upload_file_pypi("he_llo-1.1.whl", content, "he-llo", "1.1")

        impexp.export()

        mapp2 = impexp.new_import()

        with mapp2.xom.keyfs.transaction():
            stage = mapp2.xom.model.getstage(api.stagename)
            verdata = stage.get_versiondata_perstage("he_llo", "1.0")
            assert verdata["version"] == "1.0"
            verdata = stage.get_versiondata_perstage("he_llo", "1.1")
            assert verdata["version"] == "1.1"

            links = stage.get_releaselinks("he_llo")
            assert len(links) == 2
            projectname = stage.get_projectname("he-llo")
            links = stage.get_releaselinks(projectname)
            assert len(links) == 2

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

