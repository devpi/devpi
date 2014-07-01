# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import hashlib
import pytest
import re
import py
import json
import posixpath
from bs4 import BeautifulSoup

from pyramid.response import Response
from devpi_common.metadata import splitbasename
from devpi_common.url import URL
from devpi_common.archive import Archive, zip_dict
from devpi_common.viewhelp import ViewVersionLinks

import devpi_server.views
from devpi_server.views import tween_keyfs_transaction

from .functional import TestUserThings, TestIndexThings  # noqa

proj = pytest.mark.parametrize("proj", [True, False])
pytestmark = [pytest.mark.notransaction]

def getfirstlink(text):
    return BeautifulSoup(text).findAll("a")[0]

def test_simple_project(pypistage, testapp):
    name = "qpwoei"
    r = testapp.get("/root/pypi/+simple/" + name)
    assert r.status_code == 200
    assert r.headers["X-DEVPI-SERIAL"]
    assert not BeautifulSoup(r.text).findAll("a")
    path = "/%s-1.0.zip" % name
    pypistage.mock_simple(name, text='<a href="%s"/>' % path)
    r = testapp.get("/root/pypi/+simple/%s" % name)
    assert r.status_code == 200
    links = BeautifulSoup(r.text).findAll("a")
    assert len(links) == 1
    assert links[0].get("href").endswith(path)

def test_project_redirect(pypistage, testapp):
    name = "qpwoei"
    headers = {'User-Agent': str('pip/1.4.1'), "Accept": str("text/html")}

    r = testapp.get("/root/pypi/%s" % name, headers=headers)
    assert r.status_code == 302
    assert r.headers["location"].endswith("/root/pypi/+simple/%s" % name)
    # trailing slash will redirect to non trailing slash first
    r = testapp.get("/root/pypi/%s/" % name, headers=headers)
    assert r.status_code == 302
    assert r.headers["location"].endswith("/root/pypi/+simple/%s" % name)

def test_simple_project_unicode_rejected(pypistage, testapp, dummyrequest):
    from devpi_server.view_auth import RootFactory
    from devpi_server.views import PyPIView
    from pyramid.httpexceptions import HTTPClientError
    dummyrequest.registry['xom'] = testapp.xom
    dummyrequest.log = pypistage.xom.log
    dummyrequest.context = RootFactory(dummyrequest)
    view = PyPIView(dummyrequest)
    name = py.builtin._totext(b"qpw\xc3\xb6", "utf-8")
    dummyrequest.matchdict.update(user="x", index="y", name=name)
    with pytest.raises(HTTPClientError):
        view.simple_list_project()

def test_simple_url_longer_triggers_404(testapp):
    assert testapp.get("/root/pypi/+simple/pytest/1.0/").status_code == 404
    assert testapp.get("/root/pypi/+simple/pytest/1.0").status_code == 404

def test_simple_project_pypi_egg(pypistage, testapp):
    pypistage.mock_simple("py",
        """<a href="http://bb.org/download/py.zip#egg=py-dev" />""")
    r = testapp.get("/root/pypi/+simple/py")
    assert r.status_code == 200
    links = BeautifulSoup(r.text).findAll("a")
    assert len(links) == 1
    r = testapp.get("/root/pypi")
    assert r.status_code == 200

def test_simple_list(pypistage, testapp):
    pypistage.mock_simple("hello1", "<html/>")
    pypistage.mock_simple("hello2", "<html/>")
    r = testapp.get("/root/pypi/+simple/hello1", expect_errors=False)
    serial = int(r.headers["X-DEVPI-SERIAL"])
    r2 = testapp.get("/root/pypi/+simple/hello2", expect_errors=False)
    assert int(r2.headers["X-DEVPI-SERIAL"]) == serial + 1

    r = testapp.get("/root/pypi/+simple/hello3")
    assert r.status_code == 200
    assert "no such project" in r.text
    r = testapp.get("/root/pypi/+simple/")
    assert r.status_code == 200
    links = BeautifulSoup(r.text).findAll("a")
    assert len(links) == 2
    hrefs = [a.get("href") for a in links]
    assert hrefs == ["hello1", "hello2"]

def test_indexroot(testapp, model):
    with model.keyfs.transaction(write=True):
        user = model.create_user("user", "123")
        user.create_stage("index", bases=("root/pypi",))
    r = testapp.get("/user/index")
    assert r.status_code == 200

def test_indexroot_root_pypi(testapp, xom):
    r = testapp.get("/root/pypi")
    assert r.status_code == 200
    assert b"in-stage" not in r.body

@pytest.mark.parametrize("code", [-1, 500, 501, 502, 503])
def test_upstream_not_reachable(pypistage, testapp, xom, code):
    name = "whatever%d" % (code + 1)
    pypistage.mock_simple(name, status_code = code)
    r = testapp.get("/root/pypi/+simple/%s" % name)
    assert r.status_code == 502

def test_pkgserv(httpget, pypistage, testapp):
    pypistage.mock_simple("package", '<a href="/package-1.0.zip" />')
    httpget.setextfile("/package-1.0.zip", b"123")
    r = testapp.get("/root/pypi/+simple/package")
    assert r.status_code == 200
    href = getfirstlink(r.text).get("href")
    assert not posixpath.isabs(href)
    url = URL(r.request.url).joinpath(href).url
    r = testapp.get(url)
    assert r.body == b"123"

def test_pkgserv_remote_failure(httpget, pypistage, testapp):
    pypistage.mock_simple("package", '<a href="/package-1.0.zip" />')
    r = testapp.get("/root/pypi/+simple/package")
    assert r.status_code == 200
    href = getfirstlink(r.text).get("href")
    url = URL(r.request.url).joinpath(href).url
    httpget.setextfile("/package-1.0.zip", b"123", status_code=500)
    r = testapp.get(url)
    assert r.status_code == 502

def test_apiconfig(testapp):
    r = testapp.get_json("/user/name/+api", status=404)
    assert r.status_code == 404
    r = testapp.get_json("/root/pypi/+api")
    assert r.status_code == 200
    assert not "pypisubmit" in r.json["result"]

def test_apiconfig_with_outside_url(testapp):
    testapp.xom.config.args.outside_url = u = "http://outside.com/root"
    r = testapp.get_json("/root/pypi/+api")
    assert r.status_code == 200
    result = r.json["result"]
    assert "pypisubmit" not in result
    assert result["index"] == u + "/root/pypi"
    assert result["login"] == u + "/+login"
    assert result["simpleindex"] == u + "/root/pypi/+simple/"

    #for name in "pushrelease simpleindex login pypisubmit resultlog".split():
    #    assert name in r.json
    #
    #
def test_root_pypi(testapp):
    r = testapp.get("/root/pypi")
    assert r.status_code == 200

def test_register_metadata_and_get_description(mapp, testapp):
    api = mapp.create_and_use("user/name")
    metadata = {"name": "pkg1", "version": "1.0", ":action": "submit",
                "description": "hello world"}
    r = testapp.get("/user/name/+simple/pkg1")
    serial = int(r.headers["X-DEVPI-SERIAL"])
    r = testapp.post(api.pypisubmit, metadata)
    new_serial = int(r.headers["X-DEVPI-SERIAL"])
    assert new_serial == serial + 1
    assert r.status_code == 200
    r = testapp.get_json("/user/name/pkg1/1.0")
    assert r.status_code == 200
    assert "hello world" in r.json["result"]["description"]
    r = testapp.get_json("/user/name/pkg1")
    assert r.status_code == 200
    assert "1.0" in r.json["result"]

class TestSubmitValidation:
    @pytest.fixture
    def submit(self, mapp, testapp):
        class Submit:
            def __init__(self, stagename="user/dev"):
                self.stagename = stagename
                self.api = mapp.create_and_use(stagename)

            def metadata(self, metadata, code):
                return testapp.post(self.api.pypisubmit, metadata, code=code)

            def file(self, filename, content, metadata, code=200):
                if "version" not in metadata:
                    metadata["version"] = splitbasename(filename,
                                                        checkarch=False)[1]
                return mapp.upload_file_pypi(
                        filename, content,
                        metadata.get("name"), metadata.get("version"),
                        indexname=self.stagename, register=False,
                        code=code)
        return Submit()

    def test_404(self, testapp, mapp):
        testapp.post("/nouser/nostage", {"hello": ""}, code=404)
        mapp.upload_file_pypi("qlwkej", b"qwe", "name", "1.0",
                              indexname="nouser/nostage", code=404)

    def test_metadata_normalize_conflict(self, submit, testapp):
        metadata = {"name": "pKg1", "version": "1.0", ":action": "submit",
                    "description": "hello world"}
        r = submit.metadata(metadata, code=200)
        metadata = {"name": "Pkg1", "version": "1.0", ":action": "submit",
                    "description": "hello world"}
        r = submit.metadata(metadata, code=403)
        body = r.body
        if not py.builtin._istext(body):
            body = body.decode("utf-8")
        assert re.search("pKg1.*already.*registered", body)

    def test_metadata_multifield(self, submit, mapp):
        classifiers = ["Intended Audience :: Developers",
                       "License :: OSI Approved :: MIT License"]
        metadata = {"name": "Pkg1", "version": "1.0", ":action": "submit",
                    "classifiers": classifiers, "platform": ["unix", "win32"]}
        submit.metadata(metadata, code=200)
        data = mapp.getjson("/%s/Pkg1/1.0" % submit.stagename)["result"]
        assert data["classifiers"] == classifiers
        assert data["platform"] == ["unix", "win32"]

    def test_metadata_multifield_singleval(self, submit, mapp):
        classifiers = ["Intended Audience :: Developers"]
        metadata = {"name": "Pkg1", "version": "1.0", ":action": "submit",
                    "classifiers": classifiers}
        submit.metadata(metadata, code=200)
        data = mapp.getjson("/%s/Pkg1/1.0" % submit.stagename)["result"]
        assert data["classifiers"] == classifiers

    def test_metadata_UNKNOWN_handling(self, submit, mapp):
        metadata = {"name": "Pkg1", "version": "1.0", ":action": "submit",
                    "download_url": "UNKNOWN", "platform": ""}
        submit.metadata(metadata, code=200)
        data = mapp.getjson("/%s/Pkg1/1.0" % submit.stagename)["result"]
        assert not data["download_url"]
        assert not data["platform"]

    def test_upload_file(self, submit):
        metadata = {"name": "Pkg5", "version": "1.0", ":action": "submit"}
        submit.metadata(metadata, code=200)
        submit.file("pkg5-2.6.tgz", b"123", {"name": "pkg5some"}, code=400)
        submit.file("pkg5-2.6.tgz", b"123", {"name": "Pkg5"}, code=200)
        submit.file("pkg5-2.6.qwe", b"123", {"name": "Pkg5"}, code=400)
        submit.file("pkg5-2.7.tgz", b"123", {"name": "pkg5"}, code=403)

    def test_upload_use_registered_name_issue84(self, submit, mapp):
        metadata = {"name": "pkg_hello", "version":"1.0", ":action": "submit"}
        submit.metadata(metadata, code=200)
        submit.file("pkg-hello-1.0.whl", b"123", {"name": "pkg-hello",
                                              "version": "1.0"}, code=200)
        paths = mapp.get_release_paths("pkg_hello")
        assert paths[0].endswith("pkg-hello-1.0.whl")

    def test_upload_and_simple_index(self, submit, testapp):
        metadata = {"name": "Pkg5", "version": "2.6", ":action": "submit"}
        submit.metadata(metadata, code=200)
        submit.file("pkg5-2.6.tgz", b"123", {"name": "Pkg5"}, code=200)
        r = testapp.get("/%s/+simple/pkg5" % submit.stagename)
        assert r.status_code == 302

    def test_upload_and_delete_index(self, submit, testapp, mapp):
        metadata = {"name": "Pkg5", "version": "2.6", ":action": "submit"}
        submit.metadata(metadata, code=200)
        submit.file("pkg5-2.6.tgz", b"123", {"name": "Pkg5"}, code=200)
        submit.file("pkg5-2.7.tgz", b"123", {"name": "Pkg5"}, code=200)
        paths = mapp.get_release_paths("Pkg5")
        for path in paths:
            testapp.xget(200, path)
            with testapp.xom.keyfs.transaction():
                entry = testapp.xom.filestore.get_file_entry(path.strip("/"))
                assert entry.file_exists()
        mapp.delete_index(submit.stagename)
        for path in paths:
            testapp.xget(404, path)
            with testapp.xom.keyfs.transaction():
                entry = testapp.xom.filestore.get_file_entry(path.strip("/"))
                assert not entry.file_exists()

    def test_upload_twice_to_volatile(self, submit, testapp, mapp):
        metadata = {"name": "Pkg5", "version": "2.6", ":action": "submit"}
        submit.metadata(metadata, code=200)
        submit.file("pkg5-2.6.tgz", b"123", {"name": "Pkg5"}, code=200)
        path1, = mapp.get_release_paths("Pkg5")
        testapp.xget(200, path1)
        submit.file("pkg5-2.6.tgz", b"1234", {"name": "Pkg5"}, code=200)
        path2, = mapp.get_release_paths("Pkg5")
        testapp.xget(404, path1)
        testapp.xget(200, path2)

    def test_get_project_redirected(self, submit, mapp):
        metadata = {"name": "Pkg1", "version": "1.0", ":action": "submit",
                    "description": "hello world"}
        submit.metadata(metadata, code=200)
        location = mapp.getjson("/%s/pkg1" % submit.stagename, code=302)
        assert location.endswith("/Pkg1")


def test_push_non_existent(mapp, testapp, monkeypatch):
    # check that push from non-existent index results in 404
    req = dict(name="pkg5", version="2.6", targetindex="user2/dev")
    r = testapp.push("/user2/dev/", json.dumps(req), expect_errors=True)
    assert r.status_code == 404
    mapp.create_and_login_user("user1", "1")
    mapp.create_index("dev")

    # check that push to non-existent target index results in 404
    r = testapp.push("/user1/dev/", json.dumps(req), expect_errors=True)
    assert r.status_code == 404

    mapp.create_and_login_user("user2")
    mapp.create_index("dev", indexconfig=dict(acl_upload=["user2"]))
    mapp.login("user1", "1")
    # check that push of non-existent release results in 404
    r = testapp.push("/user1/dev/", json.dumps(req), expect_errors=True)
    assert r.status_code == 404
    #
    mapp.use("user1/dev")
    mapp.upload_file_pypi("pkg5-2.6.tgz", b"123", "pkg5", "2.6")
    # check that push to non-authoried existent target index results in 401
    r = testapp.push("/user1/dev", json.dumps(req), expect_errors=True)
    assert r.status_code == 401


@proj
def test_upload_and_push_internal(mapp, testapp, monkeypatch, proj):
    mapp.create_user("user1", "1")
    mapp.create_and_login_user("user2")
    mapp.create_index("prod", indexconfig=dict(acl_upload=["user1", "user2"]))
    mapp.create_index("dev", indexconfig=dict(acl_upload=["user2"]))

    mapp.login("user1", "1")
    mapp.create_index("dev")
    mapp.use("user1/dev")
    mapp.upload_file_pypi("pkg1-2.6.tgz", b"123", "pkg1", "2.6")
    content = zip_dict({"index.html": "<html/>"})
    mapp.upload_doc("pkg1.zip", content, "pkg1", "")

    # check that push is authorized and executed towards user2/prod index
    req = dict(name="pkg1", version="2.6", targetindex="user2/prod")
    r = testapp.push("/user1/dev", json.dumps(req))
    assert r.status_code == 200
    vv = get_view_version_links(testapp, "/user2/prod", "pkg1", "2.6",
                                proj=proj)
    link = vv.get_link(rel="releasefile")
    assert link.href.endswith("/pkg1-2.6.tgz")
    # we check here that the upload of docs without version was
    # automatically tied to the newest release metadata
    link = vv.get_link(rel="doczip")
    assert link.href.endswith("/pkg1-2.6.doc.zip")
    r = testapp.get(link.href)
    archive = Archive(py.io.BytesIO(r.body))
    assert 'index.html' in archive.namelist()


def test_upload_and_push_external(mapp, testapp, reqmock):
    api = mapp.create_and_use()
    mapp.upload_file_pypi("pkg1-2.6.tgz", b"123", "pkg1", "2.6")
    zipcontent = zip_dict({"index.html": "<html/>"})
    mapp.upload_doc("pkg1.zip", zipcontent, "pkg1", "")

    r = testapp.get(api.simpleindex + "pkg1")
    assert r.status_code == 200
    a = getfirstlink(r.text)
    assert "pkg1-2.6.tgz" in a.get("href")

    # get root index page
    r = testapp.get(api.index)
    assert r.status_code == 200

    # push OK
    req = dict(name="pkg1", version="2.6", posturl="http://whatever.com/",
               username="user", password="password")
    rec = reqmock.mockresponse(url=None, code=200, method="POST", data="msg")
    body = json.dumps(req).encode("utf-8")
    r = testapp.request(api.index, method="PUSH", body=body,
                        expect_errors=True)
    assert r.status_code == 200
    assert len(rec.requests) == 3
    for i in range(3):
        assert rec.requests[i].url == req["posturl"]
    req = rec.requests[2]
    # XXX properly decode www-url-encoded body and check zipcontent
    assert b"pkg1.zip" in req.body
    assert zipcontent in req.body

    # push with error
    reqmock.mockresponse(url=None, code=500, method="POST")
    r = testapp.request(api.index, method="PUSH", body=body, expect_errors=True)
    assert r.status_code == 502
    result = r.json["result"]
    assert len(result) == 1
    assert result[0][0] == 500

def test_upload_and_push_egg(mapp, testapp, reqmock):
    api = mapp.create_and_use()
    mapp.upload_file_pypi("pkg2-1.0-py27.egg", b"123", "pkg2", "1.0")
    r = testapp.get(api.simpleindex + "pkg2")
    assert r.status_code == 200
    a = getfirstlink(r.text)
    assert "pkg2-1.0-py27.egg" in a.get("href")

    # push
    req = dict(name="pkg2", version="1.0", posturl="http://whatever.com/",
               username="user", password="password")
    rec = reqmock.mockresponse(url=None, data=b"msg", code=200)
    r = testapp.push(api.index, json.dumps(req))
    assert r.status_code == 200
    assert len(rec.requests) == 2
    assert rec.requests[0].url == req["posturl"]
    assert rec.requests[1].url == req["posturl"]

def test_upload_and_delete_project(mapp, testapp):
    api = mapp.create_and_use()
    mapp.delete_project("pkg1", code=404)
    mapp.upload_file_pypi("pkg1-2.6.tgz", b"123", "pkg1", "2.6")
    mapp.upload_file_pypi("pkg1-2.7.tgz", b"123", "pkg1", "2.7")
    r = testapp.get(api.simpleindex + "pkg1")
    assert r.status_code == 200
    r = testapp.delete(api.index + "/pkg1/2.6")
    assert r.status_code == 200
    mapp.getjson(api.index + "/pkg1", code=200)
    r = testapp.delete(api.index + "/pkg1/2.7")
    assert r.status_code == 200
    mapp.getjson(api.index + "/pkg1", code=404)

def test_upload_with_acl(mapp):
    mapp.login("root")
    mapp.change_password("root", "123")
    mapp.create_user("user", "123")
    api = mapp.create_and_use()  # new context and login
    mapp.login("user", "123")
    # user cannot write to index now
    mapp.upload_file_pypi("pkg1-2.6.tgz", b"123", "pkg1", "2.6", code=403)
    mapp.login(api.user, api.password)
    mapp.set_acl(["user"])
    mapp.login("user", "123")
    # we need to skip setting the whitelist here, because the user may only
    # register and upload a package, but not modify the index
    mapp.upload_file_pypi("pkg1-2.6.tgz", b"123", "pkg1", "2.6",
                          set_whitelist=False)

def test_upload_with_jenkins(mapp, reqmock):
    mapp.create_and_use()
    mapp.set_uploadtrigger_jenkins("http://x.com/{pkgname}")
    rec = reqmock.mockresponse(code=200, url=None)
    mapp.upload_file_pypi("pkg1-2.6.tgz", b"123", "pkg1", "2.6", code=200)
    assert len(rec.requests) == 1
    assert rec.requests[0].url == "http://x.com/pkg1"
    # XXX properly decode form
    #assert args[1]["data"]["Submit"] == "Build"

def test_upload_and_testdata(mapp, testapp):
    from test_devpi_server.example import tox_result_data
    api = mapp.create_and_use()
    mapp.upload_file_pypi("pkg1-2.6.tgz", b"123", "pkg1", "2.6", code=200)
    path, = mapp.get_release_paths("pkg1")
    testapp.xget(200, path)
    import json
    r = testapp.post(path, json.dumps(tox_result_data))
    assert r.status_code == 200
    vv = get_view_version_links(testapp, api.index, "pkg1", "2.6", proj=proj)
    link = vv.get_link("toxresult")
    pkgmeta = json.loads(testapp.get(link.href).body.decode("utf8"))
    assert pkgmeta == tox_result_data
    assert link.for_href.endswith(path)


@proj
def test_upload_and_access_releasefile_meta(mapp, testapp, proj):
    api = mapp.create_and_use()
    mapp.upload_file_pypi("pkg5-2.6.tgz", b"123", "pkg5", "2.6")
    vv = get_view_version_links(testapp, api.index, "pkg5", "2.6", proj=proj)
    link = vv.get_link("releasefile")
    pkgmeta = mapp.getjson(link.href)
    assert pkgmeta["type"] == "releasefilemeta"
    assert pkgmeta["result"]["md5"] == hashlib.md5(b'123').hexdigest()


def test_upload_and_delete_project_version(mapp):
    api = mapp.create_and_use()
    mapp.delete_project("pkg1", code=404)
    mapp.upload_file_pypi("pkg1-2.6.tgz", b"123", "pkg1", "2.6")
    mapp.upload_file_pypi("pkg1-2.7.tgz", b"123", "pkg1", "2.7")
    mapp.get_simple("pkg1", code=200)
    mapp.delete_project("pkg1/1.0", code=404)
    mapp.delete_project("pkg1/2.6", code=200)
    assert mapp.getjson(api.index + "/pkg1")["result"]
    mapp.delete_project("pkg1/2.7", code=200)
    #assert mapp.getjson("/user/name/pkg1/")["status"] == 404
    mapp.getjson(api.index + "pkg1", code=404)

def test_delete_version_fails_on_non_volatile(mapp):
    mapp.create_and_use(indexconfig=dict(volatile=False))
    mapp.upload_file_pypi("pkg1-2.6.tgz", b"123", "pkg1", "2.6")
    mapp.delete_project("pkg1/2.6", code=403)


def test_upload_pypi_fails(mapp):
    mapp.upload_file_pypi(
            "pkg1-2.6.tgz", b"123", "pkg1", "2.6", code=404,
            indexname="root/pypi")

def test_delete_pypi_fails(mapp):
    mapp.login_root()
    mapp.use("root/pypi")
    mapp.delete_project("pytest/2.3.5", code=405)
    mapp.delete_project("pytest", code=405)

def test_delete_volatile_fails(mapp):
    mapp.login_root()
    mapp.create_index("test", indexconfig=dict(volatile=False))
    mapp.use("root/test")
    mapp.upload_file_pypi("pkg5-2.6.tgz", b"123", "pkg5", "2.6")
    mapp.delete_project("pkg5", code=403)

@proj
def test_upload_docs_no_version(mapp, testapp, proj):
    api = mapp.create_and_use()
    content = zip_dict({"index.html": "<html/>"})
    mapp.register_metadata(dict(name="Pkg1", version="1.0"))
    mapp.upload_doc("pkg1.zip", content, "Pkg1", "")
    vv = get_view_version_links(testapp, api.index, "Pkg1", "1.0", proj=proj)
    link = vv.get_link("doczip")
    assert link.href.endswith("/Pkg1-1.0.doc.zip")
    r = testapp.get(link.href)
    archive = Archive(py.io.BytesIO(r.body))
    assert 'index.html' in archive.namelist()

def test_upload_docs_no_project_ever_registered(mapp, testapp):
    mapp.create_and_use()
    content = zip_dict({"index.html": "<html/>"})
    mapp.upload_doc("pkg1.zip", content, "pkg1", "", code=400)

def test_upload_docs_too_large(mapp):
    from devpi_server.views import MAXDOCZIPSIZE
    mapp.create_and_use()
    content = b"*" * (MAXDOCZIPSIZE + 1)
    mapp.register_metadata(dict(name="pkg1", version="0.0"))
    mapp.upload_doc("pkg1.zip", content, "pkg1", "2.6", code=413)

@proj
def test_upload_docs(mapp, testapp, proj):
    api = mapp.create_and_use()
    content = zip_dict({"index.html": "<html/>"})
    mapp.upload_doc("pkg1.zip", content, "pkg1", "2.6", code=400)
    mapp.register_metadata({"name": "pkg1", "version": "2.6"})
    mapp.upload_doc("pkg1.zip", content, "pkg1", "2.6", code=200)
    vv = get_view_version_links(testapp, api.index, "pkg1", "2.6", proj=proj)
    link = vv.get_link(rel="doczip")
    assert link.href.endswith("/pkg1-2.6.doc.zip")
    r = testapp.get(link.href)
    archive = Archive(py.io.BytesIO(r.body))
    assert 'index.html' in archive.namelist()


def get_view_version_links(testapp, index, name, version, proj=False):
    if proj:
        url = "/".join([index, name])
        r = testapp.get_json(url, expect_errors=False)
        return ViewVersionLinks(url, r.json["result"][version])
    else:
        url = "/".join([index, name, version])
        r = testapp.get_json(url, expect_errors=False)
        return ViewVersionLinks(url, r.json["result"])


def test_wrong_login_format(testapp, mapp):
    api = mapp.getapi()
    r = testapp.post(api.login, "qweqweqwe", expect_errors=True)
    assert r.status_code == 400
    r = testapp.post_json(api.login, {"qwelk": ""}, expect_errors=True)
    assert r.status_code == 400



@pytest.mark.parametrize(["input", "expected"], [
    ({},
      dict(type="stage", volatile=True, bases=["root/pypi"])),
    ({"volatile": "False"},
      dict(type="stage", volatile=False, bases=["root/pypi"])),
    ({"volatile": "False", "bases": "root/pypi"},
      dict(type="stage", volatile=False, bases=["root/pypi"])),
    ({"volatile": "False", "bases": ["root/pypi"]},
      dict(type="stage", volatile=False, bases=["root/pypi"])),
    ({"volatile": "False", "bases": ["root/pypi"], "acl_upload": ["hello"]},
      dict(type="stage", volatile=False, bases=["root/pypi"],
           acl_upload=["hello"])),
])
def test_kvdict(input, expected):
    from devpi_server.views import getkvdict_index
    result = getkvdict_index(input)
    assert result == expected


@pytest.mark.parametrize("headers, environ, outsideurl, expected", [
    (
        {"X-outside-url": "http://outside.com"}, {},
        None, "http://outside.com/"),
    (
        {"Host": "outside3.com"}, {},
        None, "http://outside3.com/"),
    (
        {"Host": "outside3.com"}, {'wsgi.url_scheme': 'https'},
        None, "https://outside3.com/"),
    (
        {"Host": "outside3.com:3141"}, {},
        None, "http://outside3.com:3141/"),
    (
        {"Host": "outside3.com:3141"}, {'wsgi.url_scheme': 'https'},
        None, "https://outside3.com:3141/"),
    # outside url takes precedence over headers
    (
        {"X-outside-url": "http://outside.com"}, {},
        "http://outside2.com", "http://outside2.com/"),
    (
        {"Host": "outside3.com"}, {},
        "http://out.com", "http://out.com/"),
    (
        {"Host": "outside3.com"}, {'wsgi.url_scheme': 'https'},
        "http://out.com", "http://out.com/")])
def test_get_outside_url(headers, environ, outsideurl, expected):
    from devpi_server.views import get_outside_url
    from pyramid.request import Request
    request = Request.blank('/', environ=environ, headers=headers)
    url = get_outside_url(request, outsideurl)
    assert url == expected


class Test_getjson:
    @pytest.fixture
    def abort_calls(self, monkeypatch):
        l = []
        def recorder(*args, **kwargs):
            l.append((args, kwargs))
            raise SystemExit(1)
        monkeypatch.setattr(devpi_server.views, "abort", recorder)
        return l

    def test_getjson(self):
        from devpi_server.views import getjson
        from pyramid.request import Request
        request = Request({}, body=b'{"hello": "world"}')
        assert getjson(request)["hello"] == "world"

    def test_getjson_error(self, abort_calls):
        from devpi_server.views import getjson
        from pyramid.request import Request
        request = Request({}, body=b"123 123")
        with pytest.raises(SystemExit):
            getjson(request)
        assert len(abort_calls) == 1
        abort_call_args = abort_calls[0][0]
        assert abort_call_args[1] == 400

    def test_getjson_wrong_keys(self, abort_calls):
        from devpi_server.views import getjson
        from pyramid.request import Request
        request = Request({}, body=b'{"k1": "v1", "k2": "v2"')
        with pytest.raises(SystemExit):
            getjson(request, allowed_keys=["k1", "k3"])
        assert len(abort_calls) == 1
        abort_call_args = abort_calls[0][0]
        assert abort_call_args[1] == 400


class TestTweenKeyfsTransaction:
    def test_nowrite(self, xom, blank_request):
        cur_serial = xom.keyfs.get_current_serial()
        wrapped_handler = lambda r: Response("")
        handler = tween_keyfs_transaction(wrapped_handler, {"xom": xom})
        response = handler(blank_request())
        assert response.headers.get("X-DEVPI-SERIAL") == str(cur_serial)

    def test_write(self, xom, blank_request):
        cur_serial = xom.keyfs.get_current_serial()
        def wrapped_handler(request):
            with xom.keyfs.USER(user="hello").update():
                pass
            return Response("")
        handler = tween_keyfs_transaction(wrapped_handler, {"xom": xom})
        response = handler(blank_request(method="PUT"))
        assert response.headers.get("X-DEVPI-SERIAL") == str(cur_serial + 1)

    def test_restart(self, xom, blank_request):
        cur_serial = xom.keyfs.get_current_serial()
        def wrapped_handler(request):
            xom.keyfs.restart_as_write_transaction()
            with xom.keyfs.USER(user="hello").update():
                pass
            return Response("")
        handler = tween_keyfs_transaction(wrapped_handler, {"xom": xom})
        response = handler(blank_request())
        assert response.headers.get("X-DEVPI-SERIAL") == str(cur_serial + 1)
