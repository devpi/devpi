"""
Module for handling storage and proxy-streaming and caching of release files
for all indexes.

"""
from __future__ import unicode_literals
import hashlib
import mimetypes
from wsgiref.handlers import format_date_time
import py
import re
import sys
from devpi_common.metadata import splitbasename
from devpi_common.types import cached_property, parse_hash_spec
from .log import threadlog


if sys.version_info >= (3, 0):
    from urllib.parse import unquote
else:
    from urllib import unquote

_nodefault = object()


def get_default_hash_spec(content):
    #return "md5=" + hashlib.md5(content).hexdigest()
    return "sha256=" + hashlib.sha256(content).hexdigest()


def make_splitdir(hash_spec):
    parts = hash_spec.split("=")
    assert len(parts) == 2
    hash_value = parts[1]
    return hash_value[:3], hash_value[3:16]


def unicode_if_bytes(val):
    if isinstance(val, py.builtin.bytes):
        val = py.builtin._totext(val)
    return val


class FileStore:
    attachment_encoding = "utf-8"

    def __init__(self, keyfs):
        self.keyfs = keyfs

    def maplink(self, link, user, index, project):
        parts = link.torelpath().split("/")
        assert parts
        basename = unquote(parts[-1])
        if link.hash_spec:
            # we can only create 32K entries per directory
            # so let's take the first 3 bytes which gives
            # us a maximum of 16^3 = 4096 entries in the root dir
            a, b = make_splitdir(link.hash_spec)
            key = self.keyfs.STAGEFILE(user=user, index=index,
                                       hashdir_a=a, hashdir_b=b,
                                       filename=link.basename)
        else:
            dirname = "_".join(parts[:-1])
            dirname = re.sub('[^a-zA-Z0-9_.-]', '_', dirname)
            key = self.keyfs.PYPIFILE_NOMD5(
                user=user, index=index,
                dirname=unquote(dirname),
                basename=basename)
        entry = FileEntry(key, readonly=False)
        entry.url = link.geturl_nofragment().url
        # verify checksum if the entry is fresh, a file exists
        # and the link specifies a checksum.  It's a situation
        # that shouldn't happen unless some manual file system
        # intervention or corruption happened
        if link.hash_spec and entry.file_exists() and not entry.hash_spec:
            threadlog.debug("verifying checksum of %s", entry.relpath)
            err = get_checksum_error(entry.file_get_content(), link.hash_spec)
            if err:
                threadlog.error(err)
                entry.file_delete()
        entry.hash_spec = unicode_if_bytes(link.hash_spec)
        entry.project = project
        version = None
        try:
            (projectname, version, ext) = splitbasename(basename)
        except ValueError:
            pass
        # only store version on entry if we can determine it
        # since version is a meta property of FileEntry, it will return None
        # if not set, if we set it explicitly, it would waste space in the
        # database
        if version is not None:
            entry.version = version
        return entry

    def get_key_from_relpath(self, relpath):
        try:
            key = self.keyfs.tx.derive_key(relpath)
        except KeyError:
            return None
        return key

    def get_file_entry(self, relpath, readonly=True):
        key = self.get_key_from_relpath(relpath)
        if key is None:
            return None
        return self.get_file_entry_from_key(key, readonly=readonly)

    def get_file_entry_from_key(self, key, meta=_nodefault, readonly=True):
        return FileEntry(key, meta=meta, readonly=readonly)

    def store(self, user, index, basename, file_content, dir_hash_spec=None):
        if dir_hash_spec is None:
            dir_hash_spec = get_default_hash_spec(file_content)
        hashdir_a, hashdir_b = make_splitdir(dir_hash_spec)
        key = self.keyfs.STAGEFILE(user=user, index=index,
                   hashdir_a=hashdir_a, hashdir_b=hashdir_b, filename=basename)
        entry = FileEntry(key, readonly=False)
        entry.file_set_content(file_content)
        return entry


def metaprop(name):
    def fget(self):
        if self.meta is not None:
            return self.meta.get(name)

    def fset(self, val):
        val = unicode_if_bytes(val)
        if self.meta.get(name) != val:
            self.meta[name] = val
            self.key.set(self.meta)

    return property(fget, fset)


class BadGateway(Exception):
    def __init__(self, msg, code=None, url=None):
        super(BadGateway, self).__init__(msg)
        self.code = code
        self.url = url


class FileEntry(object):
    BadGateway = BadGateway
    hash_spec = metaprop("hash_spec")  # e.g. "md5=120938012"
    # BBB keep this until devpi-server 6.0.0,
    # it was required for devpi-web <= 3.5.1
    # it was used for the old scraping/crawling code
    eggfragment = metaprop("eggfragment")
    last_modified = metaprop("last_modified")
    url = metaprop("url")
    project = metaprop("project")
    version = metaprop("version")

    def __init__(self, key, meta=_nodefault, readonly=True):
        self.key = key
        self.relpath = key.relpath
        self.basename = self.relpath.split("/")[-1]
        self.readonly = readonly
        self._storepath = "/".join(("+files", str(self.relpath)))
        if meta is not _nodefault:
            self.meta = meta or {}

    @property
    def hash_value(self):
        return self.hash_spec.split("=", 1)[1]

    @property
    def hash_type(self):
        return self.hash_spec.split("=")[0]

    def check_checksum(self, content):
        if not self.hash_spec:
            return
        err = get_checksum_error(content, self.hash_spec)
        if err:
            return ValueError("%s: %s" %(self.relpath, err))

    def file_get_checksum(self, hash_type):
        return getattr(hashlib, hash_type)(self.file_get_content()).hexdigest()

    @property
    def tx(self):
        return self.key.keyfs.tx

    md5 = property(None, None)

    @cached_property
    def meta(self):
        return self.key.get(readonly=self.readonly)

    def file_exists(self):
        return self.tx.conn.io_file_exists(self._storepath)

    def file_delete(self):
        return self.tx.conn.io_file_delete(self._storepath)

    def file_size(self):
        return self.tx.conn.io_file_size(self._storepath)

    def __repr__(self):
        return "<FileEntry %r>" %(self.key)

    def file_open_read(self):
        return self.tx.conn.io_file_open(self._storepath)

    def file_get_content(self):
        return self.tx.conn.io_file_get(self._storepath)

    def file_os_path(self):
        return self.tx.conn.io_file_os_path(self._storepath)

    def file_set_content(self, content, last_modified=None, hash_spec=None):
        assert isinstance(content, bytes)
        if last_modified != -1:
            if last_modified is None:
                last_modified = unicode_if_bytes(format_date_time(None))
            self.last_modified = last_modified
        if hash_spec:
            err = get_checksum_error(content, hash_spec)
            if err:
                raise ValueError(err)
        else:
            hash_spec = get_default_hash_spec(content)
        self.hash_spec = hash_spec
        self.tx.conn.io_file_set(self._storepath, content)
        # we make sure we always refresh the meta information
        # when we set the file content. Otherwise we might
        # end up only committing file content without any keys
        # changed which will not replay correctly at a replica.
        self.key.set(self.meta)

    def gethttpheaders(self):
        assert self.file_exists()
        headers = {}
        headers[str("last-modified")] = str(self.last_modified)
        m = mimetypes.guess_type(self.basename)[0]
        headers[str("content-type")] = str(m)
        headers[str("content-length")] = str(self.file_size())
        headers[str("cache-control")] = str("max-age=365000000, immutable, public")
        return headers

    def __eq__(self, other):
        try:
            return self.relpath == other.relpath and self.key == other.key
        except AttributeError:
            return False

    def __ne__(self, other):
        return not self == other

    def __hash__(self):
        return hash(self.relpath)

    def delete(self, **kw):
        self.key.delete()
        self.meta = {}
        self.file_delete()

    def has_existing_metadata(self):
        return self.hash_spec and self.last_modified


def get_checksum_error(content, hash_spec):
    hash_algo, hash_value = parse_hash_spec(hash_spec)
    hash_type = hash_spec.split("=")[0]
    digest = hash_algo(content).hexdigest()
    if digest != hash_value:
        return "%s mismatch, got %s, expected %s" % (hash_type, digest, hash_value)
