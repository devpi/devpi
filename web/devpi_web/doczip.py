from devpi_common.archive import Archive


def doc_key(stage, name, version):
    return stage.keyfs.STAGEDOCS(
        user=stage.user.name, index=stage.index, name=name, version=version)


def devpiserver_docs_uploaded(stage, name, version, entry):
    # unpack
    key = doc_key(stage, name, version)
    # XXX locking? (unzipping could happen concurrently in theory)
    tempdir = stage.keyfs.mkdtemp(name)
    with Archive(entry.filepath.open("rb")) as archive:
        archive.extract(tempdir)
    keypath = key.filepath
    if keypath.check():
        old = keypath.new(basename="old-" + keypath.basename)
        keypath.move(old)
        tempdir.move(keypath)
        old.remove()
    else:
        keypath.dirpath().ensure(dir=1)
        tempdir.move(keypath)
    return keypath
