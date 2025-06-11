from bs4 import BeautifulSoup
from devpi_common.archive import zip_dict
from io import BytesIO
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.response import HTTPResponse
from webob.request import cgi_FieldStorage  # type: ignore[attr-defined]
import json
import pytest


pytestmark = [pytest.mark.notransaction]


def getfirstlink(text):
    return BeautifulSoup(text, "html.parser").find_all("a")[0]


def test_upload_and_push_external(mapp, testapp, reqmock):
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
    req = dict(name="pkg1", version="2.6", posturl="http://whatever.com/",
               username="user", password="password", register_project=True)
    rec = reqmock.mockresponse(url=None, code=200, method="POST", data="msg")
    body = json.dumps(req).encode("utf-8")
    r = testapp.request(api.index, method="POST", body=body,
                        expect_errors=True)
    assert r.status_code == 200
    (action_register, action_upload, action_docfile) = r.json["result"]
    assert action_register == [200, 'register', 'pkg1', '2.6']
    assert action_upload == [
        200, 'upload', f'user1/dev/+f/{hashdir}/pkg1-2.6.tgz', '']
    assert action_docfile == [200, 'docfile', 'pkg1']
    assert len(rec.requests) == 3
    for i in range(3):
        assert rec.requests[i].url == req["posturl"]
    req = rec.requests[2]
    # XXX properly decode www-url-encoded body and check zipcontent
    assert b"pkg1.zip" in req.body
    assert zipcontent in req.body

    # push with 410, which should be ignored by register, but fail upload
    rec = reqmock.mockresponse(url=None, code=410, method="POST", data="msg")
    r = testapp.request(api.index, method="POST", body=body,
                        expect_errors=True)
    assert r.status_code == 502
    (action_register, action_upload, action_docfile) = r.json["result"]
    assert action_register == [410, 'register', 'pkg1', '2.6']
    assert action_upload == [
        410, 'upload', f'user1/dev/+f/{hashdir}/pkg1-2.6.tgz', 'msg']
    assert action_docfile == [410, 'docfile', 'pkg1']

    # push with internal server error, which should fail register
    reqmock.mockresponse(url=None, code=500, method="POST")
    r = testapp.request(api.index, method="POST", body=body, expect_errors=True)
    assert r.status_code == 502
    result = r.json["result"]
    assert len(result) == 1
    assert result[0][0] == 500
    assert result[0][1] == 'register'


def test_upload_and_push_external_no_docs(mapp, testapp, reqmock):
    from devpi_server.filestore import relpath_prefix
    api = mapp.create_and_use()
    content = b"123"
    hashdir = relpath_prefix(content)
    mapp.upload_file_pypi("pkg1-2.6.tgz", content, "pkg1", "2.6")
    zipcontent = zip_dict({"index.html": "<html/>"})
    mapp.upload_doc("pkg1.zip", zipcontent, "pkg1", "")
    req = dict(name="pkg1", version="2.6", posturl="http://whatever.com/",
               username="user", password="password", no_docs=True)
    reqmock.mockresponse(url=None, code=200, method="POST", data="msg")
    body = json.dumps(req).encode()
    r = testapp.request(api.index, method="POST", body=body)
    assert r.status_code == 200
    (action_upload,) = r.json["result"]
    assert action_upload == [
        200, 'upload', f'user1/dev/+f/{hashdir}/pkg1-2.6.tgz', '']


def test_upload_and_push_external_only_docs(mapp, testapp, reqmock):
    api = mapp.create_and_use()
    content = b"123"
    mapp.upload_file_pypi("pkg1-2.6.tgz", content, "pkg1", "2.6")
    zipcontent = zip_dict({"index.html": "<html/>"})
    mapp.upload_doc("pkg1.zip", zipcontent, "pkg1", "")
    req = dict(name="pkg1", version="2.6", posturl="http://whatever.com/",
               username="user", password="password", only_docs=True)
    reqmock.mockresponse(url=None, code=200, method="POST", data="msg")
    body = json.dumps(req).encode()
    r = testapp.request(api.index, method="POST", body=body)
    assert r.status_code == 200
    (action_docfile,) = r.json["result"]
    assert action_docfile == [200, 'docfile', 'pkg1']


def test_upload_and_push_external_exception(mapp, testapp, reqmock):
    import requests
    api = mapp.create_and_use()
    mapp.upload_file_pypi("pkg1-2.6.tgz", b"123", "pkg1", "2.6")
    responses = []

    def process_request(self, request, kwargs):
        if not responses:
            raise requests.urllib3.exceptions.NewConnectionError(None, "")
        response = responses.pop(0)
        r = HTTPAdapter().build_response(request, response)
        return r
    reqmock.process_request = process_request.__get__(reqmock)

    # first test should fail during register
    req = dict(name="pkg1", version="2.6", posturl="http://whatever.com/",
               username="user", password="password", register_project=True)
    body = json.dumps(req).encode("utf-8")
    r = testapp.request(api.index, method="POST", body=body,
                        expect_errors=True)
    assert r.status_code == 502
    assert r.json['type'] == 'actionlog'
    assert len(r.json['result']) == 1
    assert r.json['result'][0][0] == -1
    assert r.json['result'][0][1] == 'exception on register:'
    assert 'NewConnectionError' in r.json['result'][0][2]

    # second test should fail during release upload
    responses.append(HTTPResponse(
        body=BytesIO(b"msg"),
        status=410, preload_content=False,
        reason="Project pre-registration is no longer required or supported, so continue directly to uploading files."))
    req = dict(name="pkg1", version="2.6", posturl="http://whatever.com/",
               username="user", password="password", register_project=True)
    body = json.dumps(req).encode("utf-8")
    r = testapp.request(api.index, method="POST", body=body,
                        expect_errors=True)
    assert r.status_code == 502
    assert r.json['type'] == 'actionlog'
    assert len(r.json['result']) == 2
    assert r.json['result'][0][0] == 410
    assert r.json['result'][0][1] == 'register'
    assert r.json['result'][1][0] == -1
    assert r.json['result'][1][1] == 'exception on release upload:'
    assert 'NewConnectionError' in r.json['result'][1][2]


def test_upload_and_push_external_metadata12(mapp, reqmock, testapp):
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
    )
    rep = reqmock.mockresponse(url=posturl, code=200, method="POST", data="msg")
    body = json.dumps(req).encode()
    r = testapp.request(api.index, method="POST", body=body,
                        expect_errors=True)
    assert r.status_code == 200
    (rec,) = rep.requests
    assert rec.url == req["posturl"]
    fs = cgi_FieldStorage(
        fp=BytesIO(rec.body),
        headers=rec.headers,
        environ={
            'REQUEST_METHOD': 'POST'})
    assert fs.getvalue("metadata_version") == "1.2"
    assert fs.getvalue('requires_python') == ">=2.7, !=3.0.*, !=3.1.*, !=3.2.*, !=3.3.*"


def test_upload_and_push_external_metadata21(mapp, reqmock, testapp):
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
    )
    rep = reqmock.mockresponse(url=posturl, code=200, method="POST", data="msg")
    body = json.dumps(req).encode()
    r = testapp.request(api.index, method="POST", body=body,
                        expect_errors=True)
    assert r.status_code == 200
    (rec,) = rep.requests
    assert rec.url == req["posturl"]
    fs = cgi_FieldStorage(
        fp=BytesIO(rec.body),
        headers=rec.headers,
        environ={
            'REQUEST_METHOD': 'POST'})
    assert fs.getvalue("metadata_version") == "2.1"
    assert fs.getvalue('description_content_type') == "text/plain"


def test_upload_and_push_external_metadata24(mapp, reqmock, testapp):
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
    )
    rep = reqmock.mockresponse(url=posturl, code=200, method="POST", data="msg")
    body = json.dumps(req).encode()
    r = testapp.request(api.index, method="POST", body=body, expect_errors=True)
    assert r.status_code == 200
    (rec,) = rep.requests
    assert rec.url == req["posturl"]
    fs = cgi_FieldStorage(
        fp=BytesIO(rec.body), headers=rec.headers, environ={"REQUEST_METHOD": "POST"}
    )
    assert fs.getvalue("metadata_version") == "2.4"
    assert fs.getvalue("license_expression") == "MIT"


def test_upload_and_push_warehouse(mapp, testapp, reqmock):
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

    responses = [
        # the "register" call isn't needed anymore. All the metadata is
        # sent together with file_upload anyway. So we get a 410 with the
        # following reason
        HTTPResponse(
            body=BytesIO(b"msg"),
            status=410, preload_content=False,
            reason="Project pre-registration is no longer required or supported, so continue directly to uploading files."),
        HTTPResponse(
            body=BytesIO(b"msg"),
            status=200, preload_content=False),
        HTTPResponse(
            body=BytesIO(b"msg"),
            status=200, preload_content=False)]
    requests = []

    def process_request(self, request, kwargs):
        response = responses.pop(0)
        r = HTTPAdapter().build_response(request, response)
        requests.append(request)
        return r
    reqmock.process_request = process_request.__get__(reqmock)

    # push OK
    req = dict(name="pkg1", version="2.6", posturl="http://whatever.com/",
               username="user", password="password", register_project=True)
    body = json.dumps(req).encode("utf-8")
    r = testapp.request(api.index, method="POST", body=body,
                        expect_errors=True)
    assert r.status_code == 200
    assert len(requests) == 3
    for i in range(3):
        assert requests[i].url == req["posturl"]
    req = requests[1]
    assert b"metadata_version" in req.body
    assert (b"%s_digest" % get_hashes(b"").get_default_type().encode()) in req.body
    assert b"pkg1-2.6.tgz" in req.body
    req = requests[2]
    assert b"metadata_version" in req.body
    # XXX properly decode www-url-encoded body and check zipcontent
    assert b"pkg1.zip" in req.body
    assert zipcontent in req.body


def test_upload_and_push_egg(mapp, testapp, reqmock):
    api = mapp.create_and_use()
    mapp.upload_file_pypi("pkg2-1.0-py27.egg", b"123", "pkg2", "1.0")
    r = testapp.xget(200, api.simpleindex + "pkg2/")
    a = getfirstlink(r.text)
    assert "pkg2-1.0-py27.egg" in a.get("href")

    # push
    req = dict(name="pkg2", version="1.0", posturl="http://whatever.com/",
               username="user", password="password")
    rep = reqmock.mockresponse(url=None, data=b"msg", code=200)
    r = testapp.push(api.index, json.dumps(req))
    assert r.status_code == 200
    (rec,) = rep.requests
    assert rec.url == req["posturl"]
