import pytest


pytestmark = [pytest.mark.notransaction]


def test_user_jsonpatch(testapp):
    testapp.put_json("/foo", dict(password="123"))
    testapp.set_auth('foo', '123')
    r = testapp.get("/foo")
    assert r.json['result'] == {'username': 'foo', 'indexes': {}}
    testapp.patch_json("/foo", [dict(op="add", path="/title", value="foo")])
    r = testapp.get("/foo")
    assert r.json['result'] == {
        'username': 'foo', 'title': 'foo', 'indexes': {}}
    testapp.patch_json("/foo", [dict(op="add", path="/description", value="bar")])
    r = testapp.get("/foo")
    assert r.json['result'] == {
        'username': 'foo', 'title': 'foo', 'description': 'bar', 'indexes': {}}
    testapp.patch_json("/foo", [dict(op="remove", path="/description")])
    r = testapp.get("/foo")
    assert r.json['result'] == {
        'username': 'foo', 'title': 'foo', 'indexes': {}}
    testapp.patch_json("/foo", [dict(op="replace", path="/title", value="bar")])
    r = testapp.get("/foo")
    assert r.json['result'] == {
        'username': 'foo', 'title': 'bar', 'indexes': {}}
    r = testapp.patch_json("/foo", [dict(op="foo")], expect_errors=True)
    assert r.status_code == 400
    assert 'Unknown operation' in r.text
    r = testapp.patch_json("/foo", [dict(op="move")], expect_errors=True)
    assert r.status_code == 400
    assert 'operation not supported' in r.text


def test_index_jsonpatch(testapp):
    testapp.put_json("/foo", dict(password="123"))
    testapp.set_auth('foo', '123')
    testapp.put_json("/foo/dev", dict())
    r = testapp.get("/foo/dev")
    assert r.json['result'] == {
        'acl_toxresult_upload': [':ANONYMOUS:'],
        'acl_upload': ['foo'],
        'bases': [],
        'mirror_whitelist': [],
        'projects': [],
        'pypi_whitelist': [],
        'type': 'stage',
        'volatile': True}
    testapp.patch_json("/foo/dev", [dict(op="add", path="/title", value="dev")])
    r = testapp.get("/foo/dev")
    assert r.json['result']['title'] == 'dev'
    testapp.patch_json("/foo/dev", [dict(op="replace", path="/title", value="ham")])
    r = testapp.get("/foo/dev")
    assert r.json['result']['title'] == 'ham'
    r = testapp.patch_json("/foo/dev", [dict(op="foo")], expect_errors=True)
    assert r.status_code == 400
    assert 'Unknown operation' in r.text
    r = testapp.patch_json("/foo/dev", [dict(op="move")], expect_errors=True)
    assert r.status_code == 400
    assert 'operation not supported' in r.text
