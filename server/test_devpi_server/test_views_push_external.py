from bs4 import BeautifulSoup
from devpi_common.archive import zip_dict
import json
import pytest


pytestmark = [pytest.mark.notransaction]


def getfirstlink(text):
    return BeautifulSoup(text, "html.parser").find_all("a")[0]


def test_upload_and_push_external(mapp, testapp):
    from devpi_server.filestore import relpath_prefix
    api = mapp.create_and_use()
    content = b"123"
    hashdir = relpath_prefix(content)
    mapp.upload_file_pypi("pkg1-2.6.tgz", content, "pkg1", "2.6")
    zipcontent = zip_dict({"index.html": "<html/>"})
    mapp.upload_doc("pkg1.zip", zipcontent, "pkg1", "")

    r = testapp.xget(200, api.simpleindex + "pkg1/")
    a = getfirstlink(r.text)
    assert "pkg1-2.6.tgz" in a.get("href")

    # get root index page
    r = testapp.xget(200, api.index)

    # push OK
    posturl = "http://whatever.com/"
    req = dict(
        name="pkg1",
        version="2.6",
        posturl=posturl,
        username="user",
        password="password",
        register_project=True,
    )
    mapp.xom.http.mockresponse(url=posturl, method="POST", content=b"msg")
    body = json.dumps(req).encode()
    r = testapp.request(api.index, method="POST", body=body)
    assert r.status_code == 200
    (action_register, action_upload, action_docfile) = r.json["result"]
    assert action_register == [200, 'register', 'pkg1', '2.6']
    assert action_upload == [
        200, 'upload', f'user1/dev/+f/{hashdir}/pkg1-2.6.tgz', '']
    assert action_docfile == [200, 'docfile', 'pkg1']
    assert len(mapp.xom.http.call_log) == 3
    assert all(x["url"] == posturl for x in mapp.xom.http.call_log)
    files_info = mapp.xom.http.call_log[-1]["kw"]["files"]["content"]
    assert files_info[0] == "pkg1.zip"
    assert files_info[1] == zipcontent

    # push with 410, which should be ignored by register, but fail upload
    mapp.xom.http.mockresponse(url=posturl, code=410, method="POST", text="msg")
    r = testapp.request(api.index, method="POST", body=body,
                        expect_errors=True)
    assert r.status_code == 502
    (action_register, action_upload, action_docfile) = r.json["result"]
    assert action_register == [410, 'register', 'pkg1', '2.6']
    assert action_upload == [
        410, 'upload', f'user1/dev/+f/{hashdir}/pkg1-2.6.tgz', 'msg']
    assert action_docfile == [410, 'docfile', 'pkg1']

    # push with internal server error, which should fail register
    mapp.xom.http.mockresponse(url=posturl, code=500, method="POST")
    r = testapp.request(api.index, method="POST", body=body, expect_errors=True)
    assert r.status_code == 502
    result = r.json["result"]
    assert len(result) == 1
    assert result[0][0] == 500
    assert result[0][1] == 'register'


def test_upload_and_push_external_no_docs(mapp, testapp):
    from devpi_server.filestore import relpath_prefix
    api = mapp.create_and_use()
    content = b"123"
    hashdir = relpath_prefix(content)
    mapp.upload_file_pypi("pkg1-2.6.tgz", content, "pkg1", "2.6")
    zipcontent = zip_dict({"index.html": "<html/>"})
    mapp.upload_doc("pkg1.zip", zipcontent, "pkg1", "")
    posturl = "http://whatever.com/"
    req = dict(
        name="pkg1",
        version="2.6",
        posturl=posturl,
        username="user",
        password="password",
        no_docs=True,
    )
    mapp.xom.http.mockresponse(url=posturl, code=200, method="POST", data="msg")
    body = json.dumps(req).encode()
    r = testapp.request(api.index, method="POST", body=body)
    assert r.status_code == 200
    (action_upload,) = r.json["result"]
    assert action_upload == [
        200, 'upload', f'user1/dev/+f/{hashdir}/pkg1-2.6.tgz', '']


def test_upload_and_push_external_only_docs(mapp, testapp):
    api = mapp.create_and_use()
    content = b"123"
    mapp.upload_file_pypi("pkg1-2.6.tgz", content, "pkg1", "2.6")
    zipcontent = zip_dict({"index.html": "<html/>"})
    mapp.upload_doc("pkg1.zip", zipcontent, "pkg1", "")
    posturl = "http://whatever.com/"
    req = dict(
        name="pkg1",
        version="2.6",
        posturl=posturl,
        username="user",
        password="password",
        only_docs=True,
    )
    mapp.xom.http.mockresponse(url=posturl, code=200, method="POST", data="msg")
    body = json.dumps(req).encode()
    r = testapp.request(api.index, method="POST", body=body)
    assert r.status_code == 200
    (action_docfile,) = r.json["result"]
    assert action_docfile == [200, 'docfile', 'pkg1']


def test_upload_and_push_external_exception(mapp, testapp):
    import httpx

    api = mapp.create_and_use()
    mapp.upload_file_pypi("pkg1-2.6.tgz", b"123", "pkg1", "2.6")

    # first test should fail during register
    posturl = "http://whatever.com/"
    req = dict(
        name="pkg1",
        version="2.6",
        posturl=posturl,
        username="user",
        password="password",
        register_project=True,
    )
    body = json.dumps(req).encode()
    exc = httpx.HTTPError("")
    mapp.xom.http.add(posturl, exception=exc)
    r = testapp.request(api.index, method="POST", body=body, expect_errors=True)
    assert r.status_code == 502
    assert r.json['type'] == 'actionlog'
    assert len(r.json['result']) == 1
    assert r.json['result'][0][0] == -1
    assert r.json['result'][0][1] == 'exception on register:'
    assert "HTTPError" in r.json["result"][0][2]

    # second test should fail during release upload
    mapp.xom.http.add(
        posturl,
        code=410,
        text="msg",
        reason="Project pre-registration is no longer required or supported, so continue directly to uploading files.",
    )
    mapp.xom.http.add(posturl, exception=exc)
    req = dict(name="pkg1", version="2.6", posturl="http://whatever.com/",
               username="user", password="password", register_project=True)
    body = json.dumps(req).encode()
    r = testapp.request(api.index, method="POST", body=body, expect_errors=True)
    assert r.status_code == 502
    assert r.json['type'] == 'actionlog'
    assert len(r.json['result']) == 2
    assert r.json['result'][0][0] == 410
    assert r.json['result'][0][1] == 'register'
    assert r.json['result'][1][0] == -1
    assert r.json['result'][1][1] == 'exception on release upload:'
    assert "HTTPError" in r.json["result"][1][2]


def test_upload_and_push_external_metadata12(mapp, testapp):
    api = mapp.create_and_use()
    mapp.upload_file_pypi("pkg1-2.6.tgz", b"123", "pkg1", "2.6")
    mapp.set_versiondata(
        dict(
            name="pkg1",
            version="2.6",
            metadata_version="1.2",
            requires_python=">=2.7, !=3.0.*, !=3.1.*, !=3.2.*, !=3.3.*",
        )
    )
    result = mapp.getjson(api.index + "/pkg1", code=200)
    verdata = result['result']['2.6']
    assert 'requires_python' in verdata
    assert verdata['requires_python'] == ">=2.7, !=3.0.*, !=3.1.*, !=3.2.*, !=3.3.*"
    posturl = "http://whatever.com/"
    req = dict(
        name="pkg1",
        version="2.6",
        posturl=posturl,
        username="user",
        password="password",
        register_project=True,
    )
    mapp.xom.http.mockresponse(url=posturl, method="POST", content=b"msg")
    body = json.dumps(req).encode()
    r = testapp.request(api.index, method="POST", body=body,
                        expect_errors=True)
    assert r.status_code == 200
    assert len(mapp.xom.http.call_log) == 2
    assert all(x["url"] == posturl for x in mapp.xom.http.call_log)
    data_info = mapp.xom.http.call_log[-1]["kw"]["data"]
    # metadata_version is overwritten on push
    assert data_info["metadata_version"] == "1.2"
    assert data_info["requires_python"] == ">=2.7, !=3.0.*, !=3.1.*, !=3.2.*, !=3.3.*"


def test_upload_and_push_external_metadata21(mapp, testapp):
    api = mapp.create_and_use()
    mapp.upload_file_pypi("pkg1-2.6.tgz", b"123", "pkg1", "2.6")
    mapp.set_versiondata(
        dict(
            name="pkg1",
            version="2.6",
            metadata_version="2.1",
            description="foo",
            description_content_type="text/plain",
        )
    )
    result = mapp.getjson(api.index + "/pkg1", code=200)
    verdata = result['result']['2.6']
    assert 'description_content_type' in verdata
    assert verdata['description_content_type'] == "text/plain"
    posturl = "http://whatever.com/"
    req = dict(
        name="pkg1",
        version="2.6",
        posturl=posturl,
        username="user",
        password="password",
        register_project=True,
    )
    mapp.xom.http.mockresponse(url=posturl, method="POST", content=b"msg")
    body = json.dumps(req).encode()
    r = testapp.request(api.index, method="POST", body=body,
                        expect_errors=True)
    assert r.status_code == 200
    assert len(mapp.xom.http.call_log) == 2
    assert all(x["url"] == posturl for x in mapp.xom.http.call_log)
    data_info = mapp.xom.http.call_log[-1]["kw"]["data"]
    assert data_info["metadata_version"] == "2.1"
    assert data_info["description_content_type"] == "text/plain"


def test_upload_and_push_external_metadata24(mapp, testapp):
    api = mapp.create_and_use()
    mapp.upload_file_pypi("pkg1-2.6.tgz", b"123", "pkg1", "2.6")
    mapp.set_versiondata(
        dict(
            name="pkg1",
            version="2.6",
            metadata_version="2.4",
            description="foo",
            license_expression="MIT",
        )
    )
    result = mapp.getjson(api.index + "/pkg1", code=200)
    verdata = result["result"]["2.6"]
    assert "license_expression" in verdata
    assert verdata["license_expression"] == "MIT"
    posturl = "http://whatever.com/"
    req = dict(
        name="pkg1",
        version="2.6",
        posturl=posturl,
        username="user",
        password="password",
        register_project=True,
    )
    mapp.xom.http.mockresponse(url=posturl, method="POST", content=b"msg")
    body = json.dumps(req).encode()
    r = testapp.request(api.index, method="POST", body=body, expect_errors=True)
    assert r.status_code == 200
    assert len(mapp.xom.http.call_log) == 2
    assert all(x["url"] == posturl for x in mapp.xom.http.call_log)
    data_info = mapp.xom.http.call_log[-1]["kw"]["data"]
    assert data_info["metadata_version"] == "2.4"
    assert data_info["license_expression"] == "MIT"


def test_upload_and_push_warehouse(mapp, testapp):
    from devpi_server.filestore import get_hashes
    # the new PyPI backend "warehouse" changes some things and they already
    # start to affect current PyPI behaviour
    api = mapp.create_and_use()
    mapp.upload_file_pypi("pkg1-2.6.tgz", b"123", "pkg1", "2.6")
    zipcontent = zip_dict({"index.html": "<html/>"})
    mapp.upload_doc("pkg1.zip", zipcontent, "pkg1", "")

    r = testapp.xget(200, api.simpleindex + "pkg1/")
    a = getfirstlink(r.text)
    assert "pkg1-2.6.tgz" in a.get("href")

    # get root index page
    r = testapp.xget(200, api.index)

    posturl = "http://whatever.com/"
    # the "register" call isn't needed anymore. All the metadata is
    # sent together with file_upload anyway. So we get a 410 with the
    # following reason
    mapp.xom.http.add(
        posturl,
        code=410,
        text="msg",
        reason="Project pre-registration is no longer required or supported, so continue directly to uploading files.",
    )
    mapp.xom.http.add(url=posturl, method="POST", content=b"msg")
    mapp.xom.http.add(url=posturl, method="POST", content=b"msg")

    # push OK
    req = dict(
        name="pkg1",
        version="2.6",
        posturl=posturl,
        username="user",
        password="password",
        register_project=True,
    )
    body = json.dumps(req).encode()
    r = testapp.request(api.index, method="POST", body=body,
                        expect_errors=True)
    assert r.status_code == 200
    assert len(mapp.xom.http.call_log) == 3
    assert all(x["url"] == posturl for x in mapp.xom.http.call_log)
    req = mapp.xom.http.call_log[1]
    data_info = req["kw"]["data"]
    assert data_info["metadata_version"] == ""
    assert f"{get_hashes(b'').get_default_type()}_digest" in data_info
    files_info = req["kw"]["files"]["content"]
    assert files_info[0] == "pkg1-2.6.tgz"
    req = mapp.xom.http.call_log[2]
    data_info = req["kw"]["data"]
    assert data_info["metadata_version"] == ""
    files_info = req["kw"]["files"]["content"]
    assert files_info[0] == "pkg1.zip"
    assert files_info[1] == zipcontent


def test_upload_and_push_egg(mapp, testapp):
    api = mapp.create_and_use()
    mapp.upload_file_pypi("pkg2-1.0-py27.egg", b"123", "pkg2", "1.0")
    r = testapp.xget(200, api.simpleindex + "pkg2/")
    a = getfirstlink(r.text)
    assert "pkg2-1.0-py27.egg" in a.get("href")

    # push
    posturl = "http://whatever.com/"
    req = dict(
        name="pkg2",
        version="1.0",
        posturl=posturl,
        username="user",
        password="password",
    )
    mapp.xom.http.mockresponse(url=posturl, method="POST", content=b"msg")
    r = testapp.push(api.index, json.dumps(req))
    assert r.status_code == 200
    (call,) = mapp.xom.http.call_log
    assert call["url"] == posturl
