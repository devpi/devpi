from __future__ import annotations

from devpi_server.config import hookimpl
from typing import TYPE_CHECKING
import pytest


if TYPE_CHECKING:
    from .plugin import Mapp
    from .plugin import MyTestApp
    from collections.abc import Callable
    from devpi_server.main import XOM


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
        'mirror_whitelist_inheritance': 'intersection',
        'projects': [],
        'type': 'stage',
        'volatile': True}
    # add to acl_upload
    testapp.patch_json("/foo/dev", ["acl_upload+=bar"])
    r = testapp.get("/foo/dev")
    assert r.json['result']['acl_upload'] == ['foo', 'bar']
    # add again to acl_upload
    testapp.patch_json("/foo/dev", ["acl_upload+=bar"])
    r = testapp.get("/foo/dev")
    assert r.json['result']['acl_upload'] == ['foo', 'bar']
    # add again to acl_upload with error
    r = testapp.patch_json("/foo/dev?error_on_noop", ["acl_upload+=bar"], expect_errors=True)
    assert r.status_code == 400
    assert r.json['message'] == "The requested modifications resulted in no changes"
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


def test_index_patch_trailing_slash(testapp):
    # add and login user
    testapp.put_json("/foo", dict(password="123"))
    testapp.set_auth('foo', '123')
    # add index
    testapp.put_json("/foo/dev/", dict())
    # remove unknown from mirror_whitelist
    r = testapp.patch_json("/foo/dev/", ["mirror_whitelist-=foo"], expect_errors=True)
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
        'mirror_url': 'https://pypi.org/simple/',
        'projects': [],
        'type': 'mirror',
        'volatile': True}
    # set volatile
    r = testapp.patch_json("/foo/dev", ["volatile=False"])
    assert r.json['result'] == {
        'mirror_url': 'https://pypi.org/simple/',
        'type': 'mirror',
        'volatile': False}


def test_patch_index_with_unknown_option(
    mapp: Mapp, testapp: MyTestApp, xom: XOM
) -> None:
    api = mapp.create_and_use("foo/dev")
    with xom.keyfs.write_transaction():
        stage = xom.model.getstage(api.stagename)
        assert "ham" not in stage.ixconfig
        assert "notify" not in stage.ixconfig
        stage._modify(notify=True, ham="baz", _keep_unknown=True)
        assert stage.ixconfig["acl_upload"] == ["foo"]
        assert stage.ixconfig["ham"] == "baz"
        assert stage.ixconfig["notify"] is True
    r = testapp.patch_json(api.index, ["acl_upload+=bar"])
    assert r.json["result"]["acl_upload"] == ["foo", "bar"]
    assert r.json["result"]["ham"] == "baz"
    assert r.json["result"]["notify"] is True
    r = testapp.patch_json(api.index, ["ham-="])
    assert "ham" not in r.json["result"]
    assert r.json["result"]["notify"] is True


def test_patch_index_with_boolean_option_from_plugin(
    makexom: Callable[..., XOM],
    makemapp: Callable[..., Mapp],
    maketestapp: Callable[..., MyTestApp],
) -> None:
    class Plugin:
        @hookimpl
        def devpiserver_indexconfig_defaults(
            self,
            index_type,  # noqa: ARG002
        ):
            return {"notify": False}

    xom = makexom(plugins=[Plugin()])
    testapp = maketestapp(xom)
    mapp = makemapp(testapp)
    api = mapp.create_and_use("foo/dev")
    r = testapp.patch_json(api.index, ["notify=true"])
    assert r.json["result"]["notify"] is True
    r = testapp.patch_json(api.index, ["notify-="])
    assert "notify" not in r.json["result"]
