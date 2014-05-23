from bs4 import BeautifulSoup
from devpi_common.archive import Archive
import json


def doc_key(stage, name, version):
    return stage.keyfs.STAGEDOCS(
        user=stage.user.name, index=stage.index, name=name, version=version)


def unpack_docs(stage, name, version, entry):
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


def iter_doc_contents(stage, name, version):
    key = doc_key(stage, name, version)
    keypath = key.filepath
    html = set()
    fjson = set()
    for entry in keypath.visit():
        if entry.basename.endswith('.fjson'):
            fjson.add(entry)
        elif entry.basename.endswith('.html'):
            html.add(entry)
    if fjson:
        for entry in fjson:
            info = json.loads(entry.read())
            yield dict(
                title=BeautifulSoup(info.get('title', '')).text,
                text=BeautifulSoup(info.get('body', '')).text,
                path=info.get('current_page_name', entry.purebasename))
    elif html:
        for entry in html:
            soup = BeautifulSoup(entry.read())
            body = soup.find('body')
            if body is None:
                continue
            title = soup.find('title')
            if title is None:
                title = ''
            else:
                title = title.text
            yield dict(
                title=title,
                text=body.text,
                path=entry.purebasename)
