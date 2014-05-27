from bs4 import BeautifulSoup
from devpi_common.archive import Archive
import json
import py


def get_unpack_path(stage, name, version):
    # XXX this should rather be in some devpi-web managed directory area
    return stage.keyfs.basedir.join(stage.user.name, stage.index,
                                    name, version, "+doc")


def unpack_docs(stage, name, version, entry):
    # unpack, maybe a bit uncarefully but in principle
    # we are not loosing the original zip file anyway
    unpack_path = get_unpack_path(stage, name, version)
    with Archive(py.io.BytesIO(entry.FILE.get())) as archive:
        archive.extract(unpack_path)
    return unpack_path


def iter_doc_contents(stage, name, version):
    unpack_path = get_unpack_path(stage, name, version)
    html = set()
    fjson = set()
    for entry in unpack_path.visit():
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
