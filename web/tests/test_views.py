from devpi_common.archive import zip_dict


def test_docs_view(mapp, testapp):
    api = mapp.create_and_use()
    content = zip_dict({"index.html": "<html/>"})
    mapp.upload_doc("pkg1.zip", content, "pkg1", "2.6", code=400)
    mapp.register_metadata({"name": "pkg1", "version": "2.6"})
    mapp.upload_doc("pkg1.zip", content, "pkg1", "2.6", code=200)
    r = testapp.get(api.index + "/pkg1/2.6/+doc/index.html")
    assert r.status_code == 200
