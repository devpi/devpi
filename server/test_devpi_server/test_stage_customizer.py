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
    assert mapp.getjson(api.index)['result']['type'] == 'unknown'
    # now check
    mapp.modify_index(api.stagename, indexconfig=dict(bases=[]), code=403)
    mapp.testapp.xdel(403, path)
    mapp.delete_project('hello', code=403)
    mapp.upload_file_pypi("hello1-1.0.tar.gz", b'content1', "hello1", "1.0", code=403)
    mapp.upload_toxresult(path, b"{}", code=403)
    # full deletion should work
    mapp.delete_index(api.stagename)
    assert 'dev' not in mapp.getjson('/%s' % api.user)['result']['indexes']
