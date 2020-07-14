from __future__ import unicode_literals

from devpi_common.archive import zip_dict
from devpi_web.indexing import ProjectIndexingInfo
from devpi_web.indexing import preprocess_project
import pytest


def test_inheritance(xom):
    with xom.keyfs.transaction(write=True):
        user = xom.model.create_user("one", "one")
        prod = user.create_stage("prod")
        prod.set_versiondata({"name": "proj", "version": "1.0"})
        dev = user.create_stage("dev", bases=(prod.name,))
        dev.set_versiondata({"name": "proj", "version": "1.1"})

    with xom.keyfs.transaction():
        stage = xom.model.getstage(dev.name)
        preprocess_project(ProjectIndexingInfo(stage=stage, name="proj"))


@pytest.mark.with_notifier
def test_doc_unpack_cleanup(mapp, testapp):
    from devpi_web.doczip import get_unpack_path
    api = mapp.create_and_use()
    content = zip_dict({
        "index.html": "<html><body>2.6</body></html>",
        "foo.html": "<html><body>Foo</body></html>"})
    mapp.set_versiondata({"name": "pkg1", "version": "2.6"})
    mapp.upload_doc("pkg1.zip", content, "pkg1", "2.6", code=200,
                    waithooks=True)
    with mapp.xom.keyfs.transaction(write=False):
        stage = mapp.xom.model.getstage(api.stagename)
        path = get_unpack_path(stage, 'pkg1', '2.6')
    testapp.xget(200, api.index + '/pkg1/2.6/+doc/foo.html')
    assert path.join('foo.html').exists()
    content = zip_dict({
        "index.html": "<html><body>2.6</body></html>"})
    mapp.upload_doc("pkg1.zip", content, "pkg1", "2.6", code=200,
                    waithooks=True)
    with mapp.xom.keyfs.transaction(write=False):
        stage = mapp.xom.model.getstage(api.stagename)
        path = get_unpack_path(stage, 'pkg1', '2.6')
    testapp.xget(404, api.index + '/pkg1/2.6/+doc/foo.html')
    assert not path.join('foo.html').exists()


@pytest.mark.with_notifier
def test_empty_doczip(mapp, testapp):
    from devpi_web.doczip import Docs
    from devpi_web.doczip import remove_docs
    from devpi_web.doczip import unpack_docs
    api = mapp.create_and_use()
    empty_doczip = b'PK\x05\x06\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00'
    mapp.set_versiondata({"name": "pkg1", "version": "2.6"})
    mapp.upload_doc("pkg1.zip", empty_doczip, "pkg1", "2.6", code=200,
                    waithooks=True)
    (name, version) = ('pkg1', '2.6')
    with mapp.xom.keyfs.transaction(write=False):
        stage = mapp.xom.model.getstage(api.stagename)
        linkstore = stage.get_linkstore_perstage(name, version)
        (link,) = linkstore.get_links(rel='doczip')
        path = unpack_docs(stage, name, version, link.entry)
    assert not path.exists()
    assert path.new(ext="hash").exists()
    assert path.new(ext="hash").read() == 'sha256=8739c76e681f900923b900c9df0ef75cf421d39cabb54650c4b9ad19b6a76d85'
    with mapp.xom.keyfs.transaction(write=False):
        stage = mapp.xom.model.getstage(api.stagename)
        assert list(Docs(stage, name, version).items()) == []
    with mapp.xom.keyfs.transaction(write=False):
        stage = mapp.xom.model.getstage(api.stagename)
        remove_docs(stage, name, version)
    # the hash file should be removed
    assert not path.new(ext="hash").exists()
