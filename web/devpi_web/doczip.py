from bs4 import BeautifulSoup
from collections.abc import MutableMapping
from contextlib import contextmanager
from devpi_common.archive import Archive
from devpi_common.types import cached_property
from devpi_common.validation import normalize_name
from devpi_server.log import threadlog
from devpi_web.compat import get_entry_hash_spec
import json
import py


try:
    import fcntl
except ImportError:
    fcntl = None  # type: ignore[assignment]


def get_unpack_path(stage, name, version):
    path = stage.xom.config.args.documentation_path
    if path is None:
        path = py.path.local(stage.keyfs.base_path) if hasattr(stage.keyfs, "base_path") else stage.keyfs.basedir
    else:
        path = py.path.local(path)
    return path.join(
        stage.user.name, stage.index, normalize_name(name), version, "+doc")


@contextmanager
def locked_unpack_path(stage, name, version, remove_lock_file=False):
    unpack_path = get_unpack_path(stage, name, version)
    # we are using the hash file as a lock file
    hash_path = unpack_path.new(ext="hash")
    try:
        with hash_path.open("a+", ensure=True) as hash_file:
            if fcntl:
                fcntl.flock(hash_file, fcntl.LOCK_EX)
            try:
                yield (hash_file, unpack_path)
            finally:
                if fcntl:
                    fcntl.flock(hash_file, fcntl.LOCK_UN)
    finally:
        if remove_lock_file and hash_path.exists():
            try:
                hash_path.remove()
            except py.error.ENOENT:
                # there is a rare possibility of a race condition here
                pass


def keep_docs_packed(config):
    return config.args.keep_docs_packed


def docs_exist(stage, name, version, entry):
    return docs_file_exists(stage, name, version, entry, 'index.html')


def docs_file_content(stage, name, version, entry, relpath):
    if not keep_docs_packed(stage.xom.config):
        return None
    with entry.file_open_read() as f:
        with Archive(f) as archive:
            return archive.read(relpath)


def docs_file_exists(stage, name, version, entry, relpath):
    if keep_docs_packed(stage.xom.config):
        with entry.file_open_read() as f:
            with Archive(f) as archive:
                try:
                    if archive.getfile(relpath):
                        return True
                except archive.FileNotExist:
                    return False
    else:
        doc_path = unpack_docs(stage, name, version, entry)
        if doc_path.join(relpath).isfile():
            return True
    return False


def docs_file_path(stage, name, version, entry, relpath):
    if keep_docs_packed(stage.xom.config):
        return None
    doc_path = unpack_docs(stage, name, version, entry)
    return doc_path.join(relpath)


def unpack_docs(stage, name, version, entry):
    # unpack, maybe a bit uncarefully but in principle
    # we are not losing the original zip file anyway
    with locked_unpack_path(stage, name, version) as (hash_file, unpack_path):
        hash_file.seek(0)
        if hash_file.read().strip() == get_entry_hash_spec(entry):
            return unpack_path
        if unpack_path.exists():
            try:
                unpack_path.remove()
            except py.error.ENOENT:
                # there is a rare possibility of a race condition here
                pass
        if not entry.file_exists():
            return unpack_path
        with entry.file_open_read() as f:
            with Archive(f) as archive:
                archive.extract(unpack_path)
        hash_file.seek(0)
        hash_file.write(get_entry_hash_spec(entry))
        hash_file.truncate()
        threadlog.debug("%s: unpacked %s-%s docs to %s",
                        stage.name, name, version, unpack_path)
        return unpack_path


class PackedEntry:
    def __init__(self, basename, body):
        self.basename = basename
        self.body = body

    def read(self, mode='rb'):
        if mode != 'rb':
            raise RuntimeError("Unsupported mode %r" % mode)
        return self.body


class Docs(MutableMapping):
    def __init__(self, stage, name, version):
        self.stage = stage
        self.keep_docs_packed = keep_docs_packed(self.stage.xom.config)
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
        if self.keep_docs_packed:
            return self._packed_entries()
        else:
            return self._unpacked_entries()

    def _packed_entries(self):
        html = set()
        fjson = set()
        with self.entry.file_open_read() as f:
            with Archive(f) as archive:
                for item in archive.namelist():
                    if item.endswith('.fjson'):
                        fjson.add(item)
                    elif item.endswith('.html'):
                        html.add(item)
                if fjson:
                    # if there is fjson, then we get structured data
                    # see http://www.sphinx-doc.org/en/master/usage/builders/index.html#serialization-builder-details
                    return {
                        k[:-6]: PackedEntry(k, archive.read(k))
                        for k in fjson}
                else:
                    return {
                        k[:-5]: PackedEntry(k, archive.read(k))
                        for k in html}

    def _unpacked_entries(self):
        unpack_path = unpack_docs(self.stage, self.name, self.version, self.entry)
        if not unpack_path.isdir():
            return {}
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
    if stage is None:
        # the stage was removed
        return
    with locked_unpack_path(stage, project, version, remove_lock_file=True) as (hash_file, directory):
        if not directory.isdir():
            threadlog.debug("ignoring lost unpacked docs: %s" % directory)
        else:
            threadlog.debug("removing unpacked docs: %s" % directory)
            directory.remove()
