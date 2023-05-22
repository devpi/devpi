"""
Module for handling storage and proxy-streaming and caching of release files
for all indexes.

"""
import hashlib
import mimetypes
from wsgiref.handlers import format_date_time
import re
from devpi_common.metadata import splitbasename
from devpi_common.types import parse_hash_spec
from devpi_server.log import threadlog
from urllib.parse import unquote


_nodefault = object()


def get_default_hash_algo():
    return hashlib.sha256


def get_default_hash_spec(content_or_file):
    return get_hash_spec(content_or_file, get_default_hash_type())


def get_default_hash_type():
    return "sha256"


def get_file_hash(fp, hash_type):
    running_hash = getattr(hashlib, hash_type)()
    while 1:
        data = fp.read(65536)
        if not data:
            break
        running_hash.update(data)
    return running_hash.hexdigest()


def get_hash_spec(content_or_file, hash_type):
    if not isinstance(content_or_file, bytes):
        if content_or_file.seekable():
            content_or_file.seek(0)
            hexdigest = get_file_hash(
                content_or_file, hash_type)
            content_or_file.seek(0)
            return f"{hash_type}={hexdigest}"
        else:
            content_or_file = content_or_file.read()
            if len(content_or_file) > 1048576:
                threadlog.warn(
                    "Read %.1f megabytes into memory in get_default_hash_spec",
                    len(content_or_file) / 1048576)
    if isinstance(content_or_file, bytes):
        running_hash = getattr(hashlib, hash_type)(content_or_file)
        return f"{running_hash.name}={running_hash.hexdigest()}"


def make_splitdir(hash_spec):
    parts = hash_spec.split("=")
    assert len(parts) == 2
    hash_value = parts[1]
    return hash_value[:3], hash_value[3:16]


def key_from_link(keyfs, link, user, index):
    if link.hash_spec:
        # we can only create 32K entries per directory
        # so let's take the first 3 bytes which gives
        # us a maximum of 16^3 = 4096 entries in the root dir
        a, b = make_splitdir(link.hash_spec)
        return keyfs.STAGEFILE(
            user=user, index=index,
            hashdir_a=a, hashdir_b=b,
            filename=link.basename)
    else:
        parts = link.torelpath().split("/")
        assert parts
        dirname = "_".join(parts[:-1])
        dirname = re.sub('[^a-zA-Z0-9_.-]', '_', dirname)
        return keyfs.PYPIFILE_NOMD5(
            user=user, index=index,
            dirname=unquote(dirname),
            basename=link.basename)


def unicode_if_bytes(val):
    if isinstance(val, bytes):
        return val.decode('ascii')
    return val


class FileStore:
    attachment_encoding = "utf-8"

    def __init__(self, keyfs):
        self.keyfs = keyfs

    def __repr__(self):
        return f"<{self.__class__.__name__} {self.keyfs!r}>"

    def maplink(self, link, user, index, project):
        key = key_from_link(self.keyfs, link, user, index)
        entry = FileEntry(key, readonly=False)
        entry.url = link.geturl_nofragment().url
        entry.hash_spec = unicode_if_bytes(link.hash_spec)
        entry.project = project
        version = None
        try:
            (projectname, version, ext) = splitbasename(link.basename)
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

    def store(self, user, index, basename, content_or_file, dir_hash_spec=None):
        # dir_hash_spec is set for toxresult files
        if dir_hash_spec is None:
            dir_hash_spec = get_default_hash_spec(content_or_file)
        hashdir_a, hashdir_b = make_splitdir(dir_hash_spec)
        key = self.keyfs.STAGEFILE(
            user=user, index=index,
            hashdir_a=hashdir_a, hashdir_b=hashdir_b, filename=basename)
        entry = FileEntry(key, readonly=False)
        entry.file_set_content(content_or_file)
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
    __slots__ = ('_meta', '_storepath', 'basename', 'key', 'readonly', 'relpath')
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
        self._meta = _nodefault
        if meta is not _nodefault:
            self._meta = meta or {}

    @property
    def index(self):
        return self.key.params['index']

    @property
    def user(self):
        return self.key.params['user']

    @property
    def hash_algo(self):
        if self.hash_spec:
            return parse_hash_spec(self.hash_spec)[0]
        else:
            return get_default_hash_algo()

    @property
    def hash_value(self):
        if self.hash_spec:
            return self.hash_spec.split("=", 1)[1]
        else:
            return self.hash_spec

    @property
    def hash_type(self):
        return self.hash_spec.split("=")[0]

    def file_get_checksum(self, hash_type):
        with self.file_open_read() as f:
            return get_file_hash(f, hash_type)

    @property
    def tx(self):
        return self.key.keyfs.tx

    md5 = property(None, None)

    @property
    def meta(self):
        if self._meta is _nodefault:
            self._meta = self.key.get(readonly=self.readonly)
        return self._meta

    def file_exists(self):
        return self.tx.conn.io_file_exists(self._storepath)

    def file_delete(self):
        return self.tx.conn.io_file_delete(self._storepath)

    def file_size(self):
        return self.tx.conn.io_file_size(self._storepath)

    def __repr__(self):
        return f"<FileEntry {self.key!r}>"

    def file_open_read(self):
        return self.tx.conn.io_file_open(self._storepath)

    def file_get_content(self):
        return self.tx.conn.io_file_get(self._storepath)

    def file_os_path(self):
        return self.tx.conn.io_file_os_path(self._storepath)

    def file_set_content(self, content_or_file, last_modified=None, hash_spec=None):
        if last_modified != -1:
            if last_modified is None:
                last_modified = unicode_if_bytes(format_date_time(None))
            self.last_modified = last_modified
        if not hash_spec:
            hash_spec = get_default_hash_spec(content_or_file)
        self.hash_spec = hash_spec
        self.tx.conn.io_file_set(self._storepath, content_or_file)
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
        self._meta = {}
        self.file_delete()

    def has_existing_metadata(self):
        return self.hash_spec and self.last_modified


def get_checksum_error(content_or_hash, relpath, hash_spec):
    if not hash_spec:
        return
    hash_algo, hash_value = parse_hash_spec(hash_spec)
    hash_type = hash_spec.split("=")[0]
    hexdigest = getattr(content_or_hash, "hexdigest", None)
    if callable(hexdigest):
        hexdigest = hexdigest()
        if content_or_hash.name != hash_type:
            return ValueError(
                f"{relpath}: hash type mismatch, "
                f"got {content_or_hash.name}, expected {hash_type}")
    else:
        hexdigest = hash_algo(content_or_hash).hexdigest()
    if hexdigest != hash_value:
        return ValueError(
            f"{relpath}: {hash_type} mismatch, "
            f"got {hexdigest}, expected {hash_value}")
