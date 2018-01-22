from __future__ import unicode_literals

import os
import sys
import pkg_resources
import py
import pytest
import json
from devpi_server.importexport import *
from devpi_server.main import Fatal
from devpi_common.archive import Archive, zip_dict
from devpi_common.metadata import Version

import devpi_server

def make_export(tmpdir, xom):
    xom.config.init_nodeinfo()
    return do_export(tmpdir, xom)

pytestmark = [pytest.mark.notransaction]


def test_has_users_or_stages(xom):
    from devpi_server.importexport import has_users_or_stages
    with xom.keyfs.transaction(write=True):
        assert not has_users_or_stages(xom)
        user = xom.model.create_user("user", "password", email="some@email.com")
        assert has_users_or_stages(xom)
        stage = xom.model.getstage("user", "dev")
        assert stage is None
        user.create_stage("dev", bases=(), type="stage", volatile=False)
        assert has_users_or_stages(xom)
        stage = xom.model.getstage("user/dev")
        stage.delete()
        user.delete()
        assert not has_users_or_stages(xom)
        stage = xom.model.getstage("root", "pypi")
        stage.delete()
        assert not has_users_or_stages(xom)
        (root,) = xom.model.get_userlist()
        root.delete()
        assert not has_users_or_stages(xom)
        assert xom.model.get_userlist() == []


def test_not_exists(tmpdir, xom):
    p = tmpdir.join("hello")
    with pytest.raises(Fatal):
         do_import(p, xom)

def test_import_wrong_dumpversion(tmpdir, xom):
    tmpdir.join("dataindex.json").write('{"dumpversion": "0"}')
    with pytest.raises(Fatal):
        do_import(tmpdir, xom)

def test_empty_export(tmpdir, xom):
    xom.config.init_nodeinfo()
    ret = make_export(tmpdir, xom)
    assert not ret
    data = json.loads(tmpdir.join("dataindex.json").read())
    assert data["dumpversion"] == Exporter.DUMPVERSION
    assert data["pythonversion"] == list(sys.version_info)
    assert data["devpi_server"] == devpi_server.__version__
    with pytest.raises(Fatal):
        make_export(tmpdir, xom)


def test_export_empty_serverdir(tmpdir, capfd, monkeypatch):
    from devpi_server.main import main
    empty = tmpdir.join("empty").ensure(dir=True)
    export = tmpdir.join("export")
    monkeypatch.setattr("devpi_server.main.configure_logging", lambda a: None)
    ret = main([
        "devpi-server",
        "--serverdir", empty.strpath,
        "--export", export.strpath])
    out, err = capfd.readouterr()
    assert empty.listdir() == []
    assert ret == 1
    assert out == ''
    assert ("The path '%s' contains no devpi-server data" % empty) in err


def test_export_import(tmpdir, capfd, monkeypatch):
    from devpi_server.main import main
    monkeypatch.setattr("devpi_server.main.configure_logging", lambda a: None)
    clean = tmpdir.join("clean").ensure(dir=True)
    ret = main([
        "devpi-server",
        "--serverdir", clean.strpath,
        "--init"])
    assert ret == 0
    export = tmpdir.join("export")
    ret = main([
        "devpi-server",
        "--serverdir", clean.strpath,
        "--export", export.strpath])
    assert ret == 0
    import_ = tmpdir.join("import")
    ret = main([
        "devpi-server",
        "--serverdir", import_.strpath,
        "--no-events",
        "--import", export.strpath])
    assert ret == 0
    out, err = capfd.readouterr()
    assert os.listdir(clean.strpath) == os.listdir(import_.strpath)
    assert 'import_all: importing finished' in out
    assert err == ''


def test_export_import_no_root_pypi(tmpdir, capfd, monkeypatch):
    from devpi_server.main import main
    monkeypatch.setattr("devpi_server.main.configure_logging", lambda a: None)
    clean = tmpdir.join("clean").ensure(dir=True)
    ret = main([
        "devpi-server",
        "--serverdir", clean.strpath,
        "--no-root-pypi",
        "--init"])
    assert ret == 0
    export = tmpdir.join("export")
    ret = main([
        "devpi-server",
        "--serverdir", clean.strpath,
        "--export", export.strpath])
    assert ret == 0
    # first we test regular import
    import_ = tmpdir.join("import")
    ret = main([
        "devpi-server",
        "--serverdir", import_.strpath,
        "--no-events",
        "--import", export.strpath])
    assert ret == 0
    out, err = capfd.readouterr()
    assert os.listdir(clean.strpath) == os.listdir(import_.strpath)
    assert 'import_all: importing finished' in out
    assert err == ''
    # now we add --no-root-pypi
    import_.remove()
    ret = main([
        "devpi-server",
        "--serverdir", import_.strpath,
        "--no-events",
        "--no-root-pypi",
        "--import", export.strpath])
    assert ret == 0
    out, err = capfd.readouterr()
    assert os.listdir(clean.strpath) == os.listdir(import_.strpath)
    assert 'import_all: importing finished' in out
    assert err == ''


def test_import_on_existing_server_data(tmpdir, xom):
    with xom.keyfs.transaction(write=True):
        xom.model.create_user("someuser", password="qwe")
    assert not make_export(tmpdir, xom)
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
    def makeimpexp(self, makemapp, gentmp):
        class ImpExp:
            def __init__(self, options=()):
                self.exportdir = gentmp()
                self.testdatadir = py.path.local(
                    pkg_resources.resource_filename(
                        'test_devpi_server', 'importexportdata'))
                self.mapp1 = makemapp(
                    options=("--export", self.exportdir) + options)

            def export(self, initnodeinfo=True):
                if initnodeinfo:
                    self.mapp1.xom.config.init_nodeinfo()
                assert self.mapp1.xom.main() == 0

            def import_testdata(self, name, options=(), plugin=None):
                path = self.testdatadir.join(name).strpath
                mapp = makemapp(
                    options=("--import", path) + options)
                if plugin is not None:
                    mapp.xom.config.pluginmanager.register(plugin)
                mapp.xom.config.init_nodeinfo()
                assert mapp.xom.main() == 0
                return mapp

            def new_import(self, options=(), plugin=None):
                mapp2 = makemapp(
                    options=("--import", str(self.exportdir)) + options)
                if plugin is not None:
                    mapp2.xom.config.pluginmanager.register(plugin)
                mapp2.xom.config.init_nodeinfo()
                assert mapp2.xom.main() == 0
                return mapp2
        return ImpExp

    @pytest.fixture
    def impexp(self, makeimpexp):
        return makeimpexp()

    def test_importing_multiple_indexes_with_releases(self, impexp):
        mapp1 = impexp.mapp1
        api1 = mapp1.create_and_use()
        content = b'content1'
        mapp1.upload_file_pypi("hello-1.0.tar.gz", content, "hello", "1.0")
        path, = mapp1.get_release_paths("hello")
        path = path.strip("/")
        stagename2 = api1.user + "/" + "dev6"
        api2 = mapp1.create_index(stagename2)
        content = b'content2'
        mapp1.upload_file_pypi("pkg1-1.0.tar.gz", content, "pkg1", "1.0")
        impexp.export()
        mapp2 = impexp.new_import()
        mapp2.use(api1.stagename)
        assert mapp2.get_release_paths('hello') == [
            '/user1/dev/+f/d0b/425e00e15a0d3/hello-1.0.tar.gz']
        mapp2.use(api2.stagename)
        assert mapp2.get_release_paths('pkg1') == [
            '/user1/dev6/+f/dab/741b6289e7dcc/pkg1-1.0.tar.gz']

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

    def test_indexes_custom_data(self, impexp):
        mapp1 = impexp.mapp1
        api = mapp1.create_and_use()
        mapp1.set_custom_data(42)
        impexp.export()
        mapp2 = impexp.new_import()
        assert api.user in mapp2.getuserlist()
        indexlist = mapp2.getindexlist(api.user)
        assert indexlist[api.stagename]["custom_data"] == 42

    def test_indexes_mirror_whitelist(self, impexp):
        mapp1 = impexp.mapp1
        api = mapp1.create_and_use()
        mapp1.set_mirror_whitelist("*")
        impexp.export()
        mapp2 = impexp.new_import()
        assert api.user in mapp2.getuserlist()
        indexlist = mapp2.getindexlist(api.user)
        assert indexlist[api.stagename]["mirror_whitelist"] == ["*"]

    @pytest.mark.parametrize('acltype', ('upload', 'toxresult_upload'))
    def test_indexes_acl(self, impexp, acltype):
        mapp1 = impexp.mapp1
        api = mapp1.create_and_use()
        mapp1.set_acl(['user1'], acltype=acltype)
        impexp.export()
        mapp2 = impexp.new_import()
        assert api.user in mapp2.getuserlist()
        indexlist = mapp2.getindexlist(api.user)
        assert indexlist[api.stagename]["acl_" + acltype] == ['user1']

    def test_acl_toxresults_upload_default(self, impexp):
        mapp = impexp.import_testdata('toxresult_upload_default')
        with mapp.xom.keyfs.transaction(write=False):
            stage = mapp.xom.model.getstage('root/dev')
            assert stage.ixconfig['acl_toxresult_upload'] == [u':ANONYMOUS:']

    def test_bases_cycle(self, caplog, impexp):
        mapp = impexp.import_testdata('basescycle')
        with mapp.xom.keyfs.transaction(write=False):
            stage = mapp.xom.model.getstage('root/dev')
            assert stage.ixconfig['bases'] == ('root/dev',)

    def test_bad_username(self, caplog, impexp):
        with pytest.raises(SystemExit):
            impexp.import_testdata('badusername')
        (record,) = caplog.getrecords('contains characters')
        assert 'root~foo.com' in record.message
        (record,) = caplog.getrecords('You should edit')
        assert 'dataindex.json' in record.message

    def test_bad_indexname(self, caplog, impexp):
        with pytest.raises(SystemExit):
            impexp.import_testdata('badindexname')
        (record,) = caplog.getrecords('contains characters')
        assert 'root/pypi!Jo' in record.message
        (record,) = caplog.getrecords('You should edit')
        assert 'dataindex.json' in record.message

    def test_normalization(self, caplog, impexp):
        mapp = impexp.import_testdata('normalization')
        with mapp.xom.keyfs.transaction(write=False):
            stage = mapp.xom.model.getstage('root/dev')
            links = stage.get_releaselinks("hello.pkg")
            assert len(links) == 1
            assert links[0].project == "hello-pkg"
            link = stage.get_link_from_entrypath(links[0].entrypath)
            assert link.entry.file_get_content() == b"content"

    def test_normalization_merge(self, caplog, impexp):
        mapp = impexp.import_testdata('normalization_merge')
        with mapp.xom.keyfs.transaction(write=False):
            stage = mapp.xom.model.getstage('root/dev')
            links = sorted(
                stage.get_releaselinks("hello.pkg"),
                key=lambda x: Version(x.version))
            assert len(links) == 2
            assert links[0].project == "hello-pkg"
            assert links[1].project == "hello-pkg"
            assert links[0].version == "1.0"
            assert links[1].version == "1.1"
            link = stage.get_link_from_entrypath(links[0].entrypath)
            assert link.entry.file_get_content() == b"content1"
            link = stage.get_link_from_entrypath(links[1].entrypath)
            assert link.entry.file_get_content() == b"content2"

    def test_upload_releasefile_with_toxresult(self, impexp):
        from test_devpi_server.example import tox_result_data
        mapp1 = impexp.mapp1
        api = mapp1.create_and_use()
        content = b'content'
        mapp1.upload_file_pypi("hello-1.0.tar.gz", content, "hello", "1.0")
        path, = mapp1.get_release_paths("hello")
        path = path.strip("/")
        mapp1.upload_toxresult("/%s" % path, json.dumps(tox_result_data))
        impexp.export()
        mapp2 = impexp.new_import()
        with mapp2.xom.keyfs.transaction(write=False):
            stage = mapp2.xom.model.getstage(api.stagename)
            links = stage.get_releaselinks("hello")
            assert len(links) == 1
            assert links[0].entry.file_get_content() == b"content"
            link = stage.get_link_from_entrypath(links[0].entrypath)
            history_log = link.get_logs()
            assert len(history_log) == 1
            assert history_log[0]['what'] == 'upload'
            assert history_log[0]['who'] == 'user1'
            assert history_log[0]['dst'] == 'user1/dev'
            results = stage.get_toxresults(link)
            assert len(results) == 1
            assert results[0] == tox_result_data
            linkstore = stage.get_linkstore_perstage(
                link.project, link.version)
            tox_link, = linkstore.get_links(rel="toxresult", for_entrypath=link)
            history_log = tox_link.get_logs()
            assert len(history_log) == 1
            assert history_log[0]['what'] == 'upload'
            assert history_log[0]['who'] == 'user1'
            assert history_log[0]['dst'] == 'user1/dev'

    def test_import_without_history_log(self, impexp):
        from test_devpi_server.example import tox_result_data
        DUMP_FILE = {
          "users": {
            "root": {
              "username": "root",
              "pwsalt": "ACs/Jhs5Tt7jKCV4xAjFzQ==",
              "pwhash": "55d0627f48422ba020337d40fbabaa684be46c47a4e53f306121fd216d9bbbaf"
            },
            "user1": {
              "username": "user1", "email": "hello@example.com",
              "pwsalt": "NYDXeETIJmAxQhMBgg3oWw==",
              "pwhash": "fce28cd56a2c6028a54133007fea8afe6ed8f3657722b213fcb19ef339b8efc6"
            }
          },
          "devpi_server": "2.0.6", "pythonversion": [2, 7, 6, "final", 0],
          "secret": "xtOAH1d8ZPhWNTMmWUdZrp9pa0urEq4Qvc7itn5SCWE=",
          "dumpversion": "2",
          "indexes": {
            "user1/dev": {
              "files": [
                {
                  "projectname": "hello", "version": "1.0",
                  "entrymapping": {
                    "projectname": "hello", "version": "1.0",
                    "last_modified": "Fri, 12 Sep 2014 13:18:55 GMT",
                    "md5": "9a0364b9e99bb480dd25e1f0284c8555"},
                  "type": "releasefile", "relpath": "user1/dev/hello/hello-1.0.tar.gz"},
                {
                  "projectname": "hello", "version": "1.0", "type": "toxresult",
                  "for_entrypath": "user1/dev/+f/9a0/364b9e99bb480/hello-1.0.tar.gz",
                  "relpath": "user1/dev/hello/9a0364b9e99bb480dd25e1f0284c8555/hello-1.0.tar.gz.toxresult0"}
              ],
              "indexconfig": {
                "bases": ["root/pypi"], "pypi_whitelist": ["hello"],
                "acl_upload": ["user1"], "uploadtrigger_jenkins": None,
                "volatile": True, "type": "stage"},
              "projects": {
                "hello": {
                  "1.0": {
                    "description": "", "license": "", "author": "", "download_url": "",
                    "summary": "", "author_email": "", "version": "1.0", "platform": [],
                    "home_page": "", "keywords": "", "classifiers": [], "name": "hello"}}}
            }
          },
          "uuid": "72f86a504b14446e98ba840d0f4609ec"
        }
        with open(impexp.exportdir.join('dataindex.json').strpath, 'w') as fp:
            fp.write(json.dumps(DUMP_FILE))

        filedir = impexp.exportdir
        for dir in ['user1', 'dev', 'hello']:
            filedir = filedir.join(dir)
            filedir.mkdir()
        with open(filedir.join('hello-1.0.tar.gz').strpath, 'w') as fp:
            fp.write('content')
        filedir = filedir.join('9a0364b9e99bb480dd25e1f0284c8555')
        filedir.mkdir()
        with open(filedir.join('hello-1.0.tar.gz.toxresult0').strpath, 'w') as fp:
            fp.write(json.dumps(tox_result_data))

        mapp2 = impexp.new_import()
        with mapp2.xom.keyfs.transaction(write=False):
            stage = mapp2.xom.model.getstage('user1/dev')
            links = stage.get_releaselinks("hello")
            assert len(links) == 1
            assert links[0].entry.file_get_content() == b"content"
            link = stage.get_link_from_entrypath(links[0].entrypath)
            history_log = link.get_logs()
            assert len(history_log) == 1
            assert history_log[0]['what'] == 'upload'
            assert history_log[0]['who'] == '<import>'
            assert history_log[0]['dst'] == 'user1/dev'
            results = stage.get_toxresults(link)
            assert len(results) == 1
            assert results[0] == tox_result_data
            linkstore = stage.get_linkstore_perstage(
                link.project, link.version)
            tox_link, = linkstore.get_links(rel="toxresult", for_entrypath=link)
            history_log = tox_link.get_logs()
            assert len(history_log) == 1
            assert history_log[0]['what'] == 'upload'
            assert history_log[0]['who'] == '<import>'
            assert history_log[0]['dst'] == 'user1/dev'

    def test_version_not_set_in_imported_versiondata(self, impexp):
        mapp1 = impexp.mapp1
        api = mapp1.create_and_use()
        content = b'content'
        mapp1.upload_file_pypi("hello-1.0.tar.gz", content, "hello", "1.0")

        # simulate a data structure where "version" is missing
        with mapp1.xom.keyfs.transaction(write=True):
            stage = mapp1.xom.model.getstage(api.stagename)
            key_projversion = stage.key_projversion("hello", "1.0")
            verdata = key_projversion.get(readonly=False)
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

    def test_same_filename_in_different_versions(self, impexp):
        # for some unknown reason, the same filename can be uploaded in two
        # different versions. Seems to be related to PEP440
        mapp1 = impexp.mapp1
        api = mapp1.create_and_use()
        content1 = b'content1'
        content2 = b'content2'
        mapp1.upload_file_pypi("hello-1.0.foo.tar.gz", content1, "hello", "1.0")
        mapp1.upload_file_pypi("hello-1.0.foo.tar.gz", content2, "hello", "1.0.foo")

        impexp.export()
        mapp2 = impexp.new_import()

        with mapp2.xom.keyfs.transaction():
            stage = mapp2.xom.model.getstage(api.stagename)
            # first
            verdata = stage.get_versiondata_perstage("hello", "1.0")
            assert verdata["version"] == "1.0"
            links = stage.get_linkstore_perstage("hello", "1.0").get_links()
            assert len(links) == 1
            assert links[0].entry.file_get_content() == b"content1"
            # second
            verdata = stage.get_versiondata_perstage("hello", "1.0.foo")
            assert verdata["version"] == "1.0.foo"
            links = stage.get_linkstore_perstage("hello", "1.0.foo").get_links()
            assert len(links) == 1
            assert links[0].entry.file_get_content() == b"content2"

    def test_dashes_in_name_issue199(self, impexp):
        mapp1 = impexp.mapp1
        api = mapp1.create_and_use()
        content = b'content'
        name = "plugin-ddpenc-3-5-1-rel"
        mapp1.upload_file_pypi(name + "-1.0.tar.gz", content, name, "1.0")
        with mapp1.xom.keyfs.transaction(write=True):
            stage = mapp1.xom.model.getstage(api.stagename)
            doccontent = zip_dict({"index.html": "<html><body>Hello"})
            link1 = stage.store_doczip( name, "1.0", content=doccontent)

        impexp.export()

        mapp2 = impexp.new_import()

        with mapp2.xom.keyfs.transaction():
            stage = mapp2.xom.model.getstage(api.stagename)
            content = stage.get_doczip(name, "1.0")
            assert content == doccontent
            linkstore = stage.get_linkstore_perstage(name, "1.0")
            link2, = linkstore.get_links(rel="doczip")
            assert link2.basename == link1.basename

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

    def test_import_replica_preserves_master_uuid(self, impexp):
        mapp1 = impexp.mapp1
        mapp1.create_and_login_user("exp", "pass")
        # fake it's a replica
        # delete cached value
        del mapp1.xom.config._master_url
        mapp1.xom.config.nodeinfo["role"] = "replica"
        mapp1.xom.config.nodeinfo["masterurl"] = "http://xyz"
        mapp1.xom.config.init_nodeinfo()
        mapp1.xom.config.set_master_uuid("mm")
        mapp1.xom.config.set_uuid("1111")
        impexp.export(initnodeinfo=False)
        mapp2 = impexp.new_import()
        assert mapp2.xom.config.nodeinfo["role"] == "standalone"
        assert mapp2.xom.config.get_master_uuid() == "mm"
        assert mapp2.xom.config.nodeinfo["uuid"] == "mm"

    def test_docs_are_preserved(self, impexp):
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
            links = stage.get_releaselinks("he-llo")
            assert len(links) == 2

    @pytest.mark.storage_with_filesystem
    @pytest.mark.skipif(not hasattr(os, 'link'),
                        reason="OS doesn't support hard links")
    def test_hard_links(self, makeimpexp):
        impexp = makeimpexp(options=('--hard-links',))
        mapp1 = impexp.mapp1
        api = mapp1.create_and_use()
        content = b'content'
        mapp1.upload_file_pypi("he-llo-1.0.tar.gz", content, "he_llo", "1.0")
        content = zip_dict({"index.html": "<html/>"})
        mapp1.upload_doc("he-llo.zip", content, "he-llo", "")

        impexp.export()

        assert impexp.exportdir.join(
          'dataindex.json').stat().nlink == 1
        assert impexp.exportdir.join(
          'user1', 'dev', 'he_llo-1.0.doc.zip').stat().nlink == 2
        assert impexp.exportdir.join(
          'user1', 'dev', 'he-llo', '1.0', 'he-llo-1.0.tar.gz').stat().nlink == 2

        mapp2 = impexp.new_import()

        with mapp2.xom.keyfs.transaction():
            stage = mapp2.xom.model.getstage(api.stagename)
            verdata = stage.get_versiondata_perstage("he_llo", "1.0")
            assert verdata["version"] == "1.0"
            links = stage.get_releaselinks("he_llo")
            assert len(links) == 1
            assert links[0].entry.file_get_content() == b'content'
            doczip = stage.get_doczip("he_llo", "1.0")
            archive = Archive(py.io.BytesIO(doczip))
            assert 'index.html' in archive.namelist()
            assert py.builtin._totext(
                archive.read("index.html"), 'utf-8') == "<html/>"

    def test_uploadtrigger_jenkins_removed_if_not_set(self, impexp):
        mapp1 = impexp.mapp1
        api = mapp1.create_and_use()
        (user, index) = api.stagename.split('/')
        with mapp1.xom.keyfs.transaction(write=True):
            stage = mapp1.xom.model.getstage(api.stagename)
            with stage.user.key.update() as userconfig:
                ixconfig = userconfig["indexes"][index]
                ixconfig["uploadtrigger_jenkins"] = None
        with mapp1.xom.keyfs.transaction():
            stage = mapp1.xom.model.getstage(api.stagename)
            assert "uploadtrigger_jenkins" in stage.ixconfig
            assert stage.ixconfig["uploadtrigger_jenkins"] is None

        impexp.export()

        mapp2 = impexp.new_import()
        with mapp2.xom.keyfs.transaction():
            stage = mapp2.xom.model.getstage(api.stagename)
            assert "uploadtrigger_jenkins" not in stage.ixconfig

    def test_import_fails_if_uploadtrigger_jenkins_set(self, impexp):
        from devpi_server.model import InvalidIndexconfig
        mapp1 = impexp.mapp1
        api = mapp1.create_and_use()
        (user, index) = api.stagename.split('/')
        with mapp1.xom.keyfs.transaction(write=True):
            stage = mapp1.xom.model.getstage(api.stagename)
            with stage.user.key.update() as userconfig:
                ixconfig = userconfig["indexes"][index]
                ixconfig["uploadtrigger_jenkins"] = "foo"
        with mapp1.xom.keyfs.transaction():
            stage = mapp1.xom.model.getstage(api.stagename)
            assert "uploadtrigger_jenkins" in stage.ixconfig
            assert stage.ixconfig["uploadtrigger_jenkins"] == "foo"

        impexp.export()

        with pytest.raises(InvalidIndexconfig) as excinfo:
            impexp.new_import()
        assert "uploadtrigger_jenkins" in excinfo.value.args[0][0]

    def test_plugin_index_config(self, impexp):
        class Plugin:
            def devpiserver_indexconfig_defaults(self, index_type):
                return {"foo_plugin": index_type}
        mapp1 = impexp.mapp1
        mapp1.xom.config.pluginmanager.register(Plugin())
        api = mapp1.create_and_use()
        with mapp1.xom.keyfs.transaction():
            stage = mapp1.xom.model.getstage(api.stagename)
            assert stage.ixconfig["foo_plugin"] == "stage"

        mapp1.set_indexconfig_option("foo_plugin", "foo")
        with mapp1.xom.keyfs.transaction():
            stage = mapp1.xom.model.getstage(api.stagename)
            assert "foo_plugin" in stage.ixconfig
            assert stage.ixconfig["foo_plugin"] == "foo"

        impexp.export()

        mapp2 = impexp.new_import(plugin=Plugin())
        with mapp2.xom.keyfs.transaction():
            stage = mapp2.xom.model.getstage(api.stagename)
            assert "foo_plugin" in stage.ixconfig
            assert stage.ixconfig["foo_plugin"] == "foo"

    @pytest.mark.nomockprojectsremote
    def test_mirror_settings_preserved(self, httpget, impexp, pypiurls):
        mapp1 = impexp.mapp1
        indexconfig = dict(
            type="mirror",
            mirror_url="http://localhost:6543/index/",
            mirror_cache_expiry="600")
        api = mapp1.create_and_use(indexconfig=indexconfig)

        impexp.export()

        httpget.mockresponse(pypiurls.simple, code=200, text="")
        httpget.mockresponse(indexconfig["mirror_url"], code=200, text="")

        mapp2 = impexp.new_import()
        result = mapp2.getjson(api.index)
        assert result["type"] == "indexconfig"
        assert result["result"] == dict(
            type="mirror",
            volatile=True,
            mirror_url="http://localhost:6543/index/",
            mirror_cache_expiry=600,
            # XXX backward compatibility with devpi-client <= 2.4.1
            acl_upload=[],
            bases=[],
            pypi_whitelist=[],
            # XXX end
            projects=[])

    @pytest.mark.nomockprojectsremote
    def test_no_mirror_releases_touched(self, httpget, impexp, pypiurls):
        mapp1 = impexp.mapp1
        indexconfig = dict(
            type="mirror",
            mirror_url="http://localhost:6543/index/")
        api = mapp1.create_and_use(indexconfig=indexconfig)

        httpget.mockresponse(
            pypiurls.simple, code=200,
            text='<a href="pytest">pytest</a>')
        httpget.mockresponse(
            indexconfig["mirror_url"], code=200,
            text='<a href="devpi">devpi</a>')

        impexp.export()

        assert os.listdir(impexp.exportdir.strpath) == ['dataindex.json']

        httpget.mockresponse(pypiurls.simple, code=200, text="")
        httpget.mockresponse(indexconfig["mirror_url"], code=200, text="")

        mapp2 = impexp.new_import()
        result = mapp2.getjson(api.index)
        assert result["type"] == "indexconfig"
        assert result["result"] == dict(
            type="mirror",
            volatile=True,
            mirror_url="http://localhost:6543/index/",
            # XXX backward compatibility with devpi-client <= 2.4.1
            acl_upload=[],
            bases=[],
            pypi_whitelist=[],
            # XXX end
            projects=[])
