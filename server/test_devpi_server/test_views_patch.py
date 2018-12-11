import pytest


pytestmark = [pytest.mark.notransaction]


def test_index_patch(testapp):
    # add and login user
    testapp.put_json("/foo", dict(password="123"))
    testapp.set_auth('foo', '123')
    # add index
    testapp.put_json("/foo/dev", dict())
    r = testapp.get("/foo/dev")
    # check defaults
    assert r.json['result'] == {
        'acl_toxresult_upload': [':ANONYMOUS:'],
        'acl_upload': ['foo'],
        'bases': [],
        'mirror_whitelist': [],
        'projects': [],
        'pypi_whitelist': [],
        'type': 'stage',
        'volatile': True}
    # add to acl_upload
    testapp.patch_json("/foo/dev", ["acl_upload+=bar"])
    r = testapp.get("/foo/dev")
    assert r.json['result']['acl_upload'] == ['foo', 'bar']
    # remove from acl_upload
    testapp.patch_json("/foo/dev", ["acl_upload-=bar"])
    r = testapp.get("/foo/dev")
    assert r.json['result']['acl_upload'] == ['foo']
    # add to bases
    testapp.patch_json("/foo/dev", ["bases+=root/pypi"])
    r = testapp.get("/foo/dev")
    assert r.json['result']['bases'] == ['root/pypi']
    # remove from bases
    testapp.patch_json("/foo/dev", ["bases-=root/pypi"])
    r = testapp.get("/foo/dev")
    assert r.json['result']['bases'] == []
    # add to mirror_whitelist
    testapp.patch_json("/foo/dev", ["mirror_whitelist+=foo", "mirror_whitelist+=bar"])
    r = testapp.get("/foo/dev")
    assert r.json['result']['mirror_whitelist'] == ['foo', 'bar']
    # remove from mirror_whitelist
    testapp.patch_json("/foo/dev", ["mirror_whitelist-=foo"])
    r = testapp.get("/foo/dev")
    assert r.json['result']['mirror_whitelist'] == ['bar']
    # remove unknown from mirror_whitelist
    r = testapp.patch_json("/foo/dev", ["mirror_whitelist-=foo"], expect_errors=True)
    assert r.status_code == 400
    assert r.json['message'] == "The 'mirror_whitelist' setting doesn't have value 'foo'"


def test_mirror_index_patch(testapp):
    # add and login user
    testapp.put_json("/foo", dict(password="123"))
    testapp.set_auth('foo', '123')
    # add mirror index
    testapp.put_json("/foo/dev", dict(
        type='mirror',
        mirror_url='https://pypi.org/simple/'))
    r = testapp.get("/foo/dev")
    # check defaults
    assert r.json['result'] == {
        'acl_upload': [],
        'bases': [],
        'mirror_url': 'https://pypi.org/simple/',
        'projects': [],
        'pypi_whitelist': [],
        'type': 'mirror',
        'volatile': True}
    # set volatile
    r = testapp.patch_json("/foo/dev", ["volatile=False"])
    assert r.json['result'] == {
        'acl_upload': [],
        'bases': [],
        'mirror_url': 'https://pypi.org/simple/',
        'pypi_whitelist': [],
        'type': 'mirror',
        'volatile': False}
