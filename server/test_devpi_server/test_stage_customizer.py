# -*- coding: utf-8 -*-
from __future__ import unicode_literals
from devpi_server.config import hookimpl
import pytest


pytestmark = [pytest.mark.notransaction]


def make_stage_plugin(cls, name="mystage"):
    class Plugin:
        @hookimpl
        def devpiserver_get_stage_customizer_classes(self):
            return [(name, cls)]

    return Plugin()


def test_permissions_for_unknown_index(mapp, xom):
    from devpi_server.model import ReadonlyIndex
    api = mapp.create_and_use()
    mapp.upload_file_pypi("hello-1.0.tar.gz", b'content', "hello", "1.0")
    (path,) = mapp.get_release_paths("hello")
    assert 'dev' in mapp.getjson('/%s' % api.user)['result']['indexes']
    assert mapp.getjson(api.index)['result']['type'] == 'stage'
    assert mapp.getjson(api.index)['result']['projects'] == ['hello']
    # change index type to unknown
    with xom.keyfs.transaction(write=True):
        stage = xom.model.getstage(api.stagename)
        with stage.user.key.update() as userconfig:
            userconfig["indexes"][stage.index]['type'] = 'unknown'
    with xom.keyfs.transaction(write=True):
        stage = xom.model.getstage(api.stagename)
        # first check direct stage access
        with pytest.raises(ReadonlyIndex):
            stage.modify(**dict(stage.ixconfig, bases=[]))
        with pytest.raises(ReadonlyIndex):
            stage.set_versiondata(
                dict(name="hello", version="1.0", requires_python=">=3.5"))
        with pytest.raises(ReadonlyIndex):
            stage.add_project_name("foo")
        with pytest.raises(ReadonlyIndex):
            stage.store_releasefile("foo", "2.0", "foo-2.0.zip", b'123')
        with pytest.raises(ReadonlyIndex):
            stage.store_doczip("foo", "2.0", b'456')
        link_store = stage.get_linkstore_perstage("hello", "1.0")
        (link,) = link_store.get_links()
        with pytest.raises(ReadonlyIndex):
            stage.store_toxresult(link, {})
    assert mapp.getjson(api.index)['result']['type'] == 'unknown'
    # now check via views, which are protected by permissions most of the time
    mapp.modify_index(api.stagename, indexconfig=dict(bases=[]), code=403)
    mapp.testapp.xdel(403, path)
    mapp.delete_project('hello', code=403)
    mapp.upload_file_pypi("hello1-1.0.tar.gz", b'content1', "hello1", "1.0", code=403)
    mapp.upload_toxresult(path, b"{}", code=403)
    # full deletion should work
    mapp.delete_index(api.stagename)
    assert 'dev' not in mapp.getjson('/%s' % api.user)['result']['indexes']


def test_indexconfig_items(makemapp, maketestapp, makexom):
    from devpi_server.model import ensure_list

    class MyStageCustomizer(object):
        def get_possible_indexconfig_keys(self):
            return ("bar", "ham")

        def normalize_indexconfig_value(self, key, value):
            if key == "bar":
                return ensure_list(value)
            if key == "ham":
                return value

        def validate_config(self, oldconfig, newconfig):
            if "bar" not in newconfig:
                raise self.InvalidIndexconfig(["requires bar"])

    xom = makexom(plugins=[make_stage_plugin(MyStageCustomizer)])
    testapp = maketestapp(xom)
    mapp = makemapp(testapp)
    user = 'user'
    password = '123'
    mapp.create_and_login_user(user, password=password)
    # test missing setting
    mapp.create_index(
        'user/foo',
        indexconfig=dict(type='mystage'),
        code=400)
    # test list conversion
    api = mapp.create_index(
        'user/foo',
        indexconfig=dict(type='mystage', bar="foo"))
    result = mapp.getjson(api.index)
    assert result['result']['bar'] == ['foo']
    assert 'ham' not in result['result']
    # test passing list directly
    api = mapp.create_index(
        'user/dev',
        indexconfig=dict(type='mystage', bar=["dev"]))
    result = mapp.getjson(api.index)
    assert result['result']['bar'] == ['dev']
    assert 'ham' not in result['result']
    # test optional setting
    api = mapp.create_index(
        'user/ham',
        indexconfig=dict(type='mystage', bar=["dev"], ham="something"))
    result = mapp.getjson(api.index)
    assert result['result']['bar'] == ['dev']
    assert result['result']['ham'] == 'something'


def test_validate_config(makemapp, maketestapp, makexom):
    class MyStageCustomizer(object):
        def validate_config(self, oldconfig, newconfig):
            errors = []
            if len(oldconfig.get('bases', [])) > len(newconfig.get('bases', [])):
                errors.append("You can't have fewer bases than before.")
            if errors:
                raise self.InvalidIndexconfig(errors)

    xom = makexom(plugins=[make_stage_plugin(MyStageCustomizer)])
    testapp = maketestapp(xom)
    mapp = makemapp(testapp)
    user = 'user'
    password = '123'
    mapp.create_and_login_user(user, password=password)
    api = mapp.create_index('user/foo')
    api = mapp.create_index('user/dev', indexconfig=dict(type='mystage'))
    result = mapp.getjson(api.index)
    assert result['result']['bases'] == []
    # add a base
    testapp.patch_json(api.index, ['bases+=user/foo'])
    result = mapp.getjson(api.index)
    assert result['result']['bases'] == ['user/foo']
    # try to remove a base
    r = testapp.patch_json(api.index, ['bases-=user/foo'], expect_errors=True)
    assert r.status_code == 400
    assert r.json['message'] == "You can't have fewer bases than before."
    result = mapp.getjson(api.index)
    assert result['result']['bases'] == ['user/foo']


def test_on_modified(makemapp, maketestapp, makexom):
    class MyStageCustomizer(object):
        def on_modified(self, request, oldconfig):
            if request.headers.get('X-Fail'):
                request.apifatal(400, request.headers['X-Fail'])

    xom = makexom(plugins=[make_stage_plugin(MyStageCustomizer)])
    testapp = maketestapp(xom)
    mapp = makemapp(testapp)
    user = 'user'
    password = '123'
    mapp.create_and_login_user(user, password=password)
    api = mapp.create_index('user/dev', indexconfig=dict(type='mystage'))
    r = testapp.patch_json(
        api.index, ['bases+=user/dev'],
        headers={'X-Fail': str('foo')}, expect_errors=True)
    assert r.status_code == 400
    assert r.json['message'] == "foo"
    result = mapp.getjson(api.index)
    assert result['result']['bases'] == []
    r = testapp.patch_json(
        api.index, ['bases+=user/dev'])
    assert r.status_code == 200
    result = mapp.getjson(api.index)
    assert result['result']['bases'] == ['user/dev']


def test_on_modified_http_exception(makemapp, maketestapp, makexom):
    from pyramid.httpexceptions import HTTPClientError

    class MyStageCustomizer(object):
        def on_modified(self, request, oldconfig):
            raise HTTPClientError

    xom = makexom(plugins=[make_stage_plugin(MyStageCustomizer)])
    testapp = maketestapp(xom)
    mapp = makemapp(testapp)
    user = 'user'
    password = '123'
    mapp.create_and_login_user(user, password=password)
    r = testapp.put_json(
        '/user/dev', dict(type='mystage'), expect_errors=True)
    assert r.status_code == 500
    assert "request.apifatal instead" in r.json['message']


def test_package_filters(makemapp, maketestapp, makexom):
    class MyStageCustomizer(object):
        def get_projects_filter_iter(self, projects):
            for project in projects:
                yield project != 'pkg'

        def get_versions_filter_iter(self, project, versions):
            for version in versions:
                yield version != '1.0'

        def get_simple_links_filter_iter(self, project, links):
            for key, href, require_python in links:
                yield '1.0' not in key

    xom = makexom(plugins=[make_stage_plugin(MyStageCustomizer)])
    testapp = maketestapp(xom)
    mapp = makemapp(testapp)
    user = 'user'
    password = '123'
    mapp.create_and_login_user(user, password=password)
    api = mapp.create_index('user/foo')
    mapp.upload_file_pypi("hello-1.0.tar.gz", b'hello10', "hello", "1.0")
    mapp.upload_file_pypi("hello-1.1.tar.gz", b'hello11', "hello", "1.1")
    mapp.upload_file_pypi("pkg-1.0.tar.gz", b'pkg10', "pkg", "1.0")
    mapp.upload_file_pypi("pkg-1.2.tar.gz", b'pkg12', "pkg", "1.2")
    assert len(mapp.getreleaseslist('hello')) == 2
    assert len(mapp.getreleaseslist('pkg')) == 2
    with xom.keyfs.transaction(write=False):
        stage = xom.model.getstage('user/foo')
        assert stage.get_latest_version_perstage('hello') == '1.1'
        assert stage.get_latest_version_perstage('pkg') == '1.2'
        assert stage.get_latest_version('hello') == '1.1'
        assert stage.get_latest_version('pkg') == '1.2'
        assert stage.has_project('hello')
        assert stage.has_project('pkg')
    r = mapp.testapp.get(api.simpleindex)
    assert '>hello<' in r.text
    assert '>pkg<' in r.text
    r = mapp.get_simple('hello')
    assert 'hello-1.0.tar.gz' in r.text
    assert 'hello-1.1.tar.gz' in r.text
    r = mapp.get_simple('pkg')
    assert 'pkg-1.0.tar.gz' in r.text
    assert 'pkg-1.2.tar.gz' in r.text
    api = mapp.create_index('user/dev', indexconfig=dict(
        type='mystage', bases='user/foo'))
    assert len(mapp.getreleaseslist('hello')) == 1
    assert mapp.getreleaseslist('pkg', code=404) is None
    with xom.keyfs.transaction(write=False):
        stage = xom.model.getstage('user/dev')
        assert stage.get_latest_version_perstage('hello') is None
        assert stage.get_latest_version_perstage('pkg') is None
        assert stage.get_latest_version('hello') == '1.1'
        assert stage.get_latest_version('pkg') is None
        assert stage.has_project('hello')
        assert not stage.has_project('pkg')
    r = mapp.testapp.get(api.simpleindex)
    assert '>hello<' in r.text
    assert '>pkg<' not in r.text
    r = mapp.get_simple('hello')
    assert 'hello-1.0.tar.gz' not in r.text
    assert 'hello-1.1.tar.gz' in r.text
    mapp.get_simple('pkg', code=404)
