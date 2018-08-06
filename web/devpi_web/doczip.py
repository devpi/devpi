from __future__ import unicode_literals
try:
    from UserDict import DictMixin
except ImportError:
    from collections import MutableMapping as DictMixin
from bs4 import BeautifulSoup
from devpi_common.archive import Archive
from devpi_common.types import cached_property
from devpi_common.validation import normalize_name
from devpi_server.log import threadlog
import json
import os
import shutil


def get_unpack_path(stage, name, version):
    # XXX this should rather be in some devpi-web managed directory area
    return stage.keyfs.basedir.join(stage.user.name, stage.index,
                                    normalize_name(name), version, "+doc")


def unpack_docs(stage, name, version, entry):
    # unpack, maybe a bit uncarefully but in principle
    # we are not loosing the original zip file anyway
    unpack_path = get_unpack_path(stage, name, version)
    hash_path = unpack_path.join('.hash')
    if hash_path.exists():
        with hash_path.open() as f:
            if f.read().strip() == entry.hash_spec:
                return unpack_path
    if unpack_path.exists():
        unpack_path.remove()
    with entry.file_open_read() as f:
        with Archive(f) as archive:
            archive.extract(unpack_path)
    with hash_path.open('w') as f:
        f.write(entry.hash_spec)
    threadlog.debug("%s: unpacked %s-%s docs to %s",
                    stage.name, name, version, unpack_path)
    return unpack_path


class Docs(DictMixin):
    def __init__(self, stage, name, version):
        self.stage = stage
        self.name = name
        self.version = version
        self.entry = None
        if version is not None:
            linkstore = stage.get_linkstore_perstage(name, version)
            links = linkstore.get_links(rel='doczip')
            if links:
                self.entry = links[0].entry

    def exists(self):
        return self.entry is not None and self.entry.file_exists()

    @cached_property
    def _entries(self):
        if not self.exists():
            # this happens on import, when the metadata is registered, but the docs
            # aren't uploaded yet
            threadlog.warn("Tried to access %s, but it doesn't exist.", self.unpack_path)
            return {}
        unpack_path = unpack_docs(self.stage, self.name, self.version, self.entry)
        html = []
        fjson = []
        for entry in unpack_path.visit():
            basename = entry.basename
            if basename.endswith('.fjson'):
                fjson.append(entry)
            elif basename.endswith('.html'):
                html.append(entry)
        if fjson:
            # if there is fjson, then we get structured data
            # see http://www.sphinx-doc.org/en/master/usage/builders/index.html#serialization-builder-details
            return {x.relto(unpack_path)[:-6]: x for x in fjson}
        else:
            return {x.relto(unpack_path)[:-5]: x for x in html}

    def keys(self):
        return self._entries.keys()

    def __len__(self):
        return len(self.keys())

    def __iter__(self):
        return iter(self.keys())

    def __delitem__(self, name):
        raise NotImplementedError

    def __setitem__(self, name, value):
        raise NotImplementedError

    def __getitem__(self, name):
        entry = self._entries[name]
        if entry.basename.endswith('.fjson'):
            info = json.loads(entry.read())
            return dict(
                title=BeautifulSoup(info.get('title', ''), "html.parser").text,
                text=BeautifulSoup(info.get('body', ''), "html.parser").text,
                path=info.get('current_page_name', name))
        else:
            soup = BeautifulSoup(entry.read(mode='rb'), "html.parser")
            body = soup.find('body')
            if body is None:
                return
            title = soup.find('title')
            if title is None:
                title = ''
            else:
                title = title.text
            return dict(
                title=title,
                text=body.text,
                path=name)


def remove_docs(stage, project, version):
    directory = str(stage.keyfs.basedir.join(
        stage.user.name,
        stage.index,
        project,
        version,
        "+doc"
    ))
    if not os.path.isdir(directory):
        threadlog.debug("ignoring lost unpacked docs: %s" % directory)
    else:
        threadlog.debug("removing unpacked docs: %s" % directory)
        shutil.rmtree(directory)
