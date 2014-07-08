from __future__ import unicode_literals

from devpi_web.indexing import preprocess_project


def test_inheritance(xom):
    with xom.keyfs.transaction(write=True):
        user = xom.model.create_user("one", "one")
        prod = user.create_stage("prod")
        prod.set_versiondata({"name": "proj", "version": "1.0"})
        dev = user.create_stage("dev", bases=(prod.name,))
        dev.set_versiondata({"name": "proj", "version": "1.1"})

    with xom.keyfs.transaction():
        stage = xom.model.getstage(dev.name)
        preprocess_project(stage, "proj")
