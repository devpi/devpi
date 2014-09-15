"""
Module for handling storage and proxy-streaming and caching of release files
for all indexes.

"""
from __future__ import unicode_literals
import hashlib
import mimetypes
from wsgiref.handlers import format_date_time
from devpi_common.types import cached_property
from .keyfs import _nodefault
from .log import threadlog

log = threadlog

class FileStore:
    attachment_encoding = "utf-8"

    def __init__(self, xom):
        self.xom = xom
        self.keyfs = xom.keyfs
        self.storedir = self.keyfs.basedir.ensure("+files", dir=1)

    def maplink(self, link):
        if link.md5:
            assert len(link.md5) == 32
            # we can only create 32K entries per directory
            # so let's take the first 3 bytes which gives
            # us a maximum of 16^3 = 4096 entries in the root dir
            md5a, md5b = split_md5(link.md5)
            key = self.keyfs.STAGEFILE(user="root", index="pypi",
                                       md5a=md5a, md5b=md5b,
                                       filename=link.basename)
        else:
            parts = link.torelpath().split("/")
            assert parts
            dirname = "_".join(parts[:-1])
            key = self.keyfs.PYPIFILE_NOMD5(user="root", index="pypi",
                   dirname=dirname,
                   basename=parts[-1])
        entry = FileEntry(self.xom, key)
        entry.url = link.geturl_nofragment().url
        entry.eggfragment = link.eggfragment
        if link.md5 != entry.md5:
            if entry.file_exists():
                log.info("replaced md5, deleting stale %s" % entry.relpath)
                entry.file_delete()
            else:
                if entry.md5:
                    log.info("replaced md5 info for %s" % entry.relpath)
        entry.md5 = link.md5
        return entry

    def get_file_entry(self, relpath):
        try:
            key = self.keyfs.derive_key(relpath)
        except KeyError:
            return None
        return FileEntry(self.xom, key)

    def get_file_entry_raw(self, key, meta):
        return FileEntry(self.xom, key, meta=meta)

    def store(self, user, index, basename, file_content, md5dir=None):
        if md5dir is None:
            md5 = hashlib.md5(file_content).hexdigest()
            md5a, md5b = split_md5(md5)
        else:
            md5a, md5b = md5dir.split("/")
        key = self.keyfs.STAGEFILE(
            user=user, index=index, md5a=md5a, md5b=md5b, filename=basename)
        entry = FileEntry(self.xom, key)
        entry.file_set_content(file_content)
        return entry

def metaprop(name):
    def fget(self):
        if self.meta is not None:
            return self.meta.get(name)
    def fset(self, val):
        self.meta[name] = val
        self.key.set(self.meta)
    return property(fget, fset)


class FileEntry(object):
    class BadGateway(Exception):
        pass

    md5 = metaprop("md5")
    eggfragment = metaprop("eggfragment")
    last_modified = metaprop("last_modified")
    url = metaprop("url")
    projectname = metaprop("projectname")
    version = metaprop("version")

    def __init__(self, xom, key, meta=_nodefault, md5=_nodefault):
        self.xom = xom
        self.key = key
        self.relpath = key.relpath
        self.basename = self.relpath.split("/")[-1]
        self._filepath = str(self.xom.filestore.storedir.join(self.relpath))
        if meta is not _nodefault:
            self.meta = meta or {}
        elif md5 is not _nodefault:
            self.meta = {"md5": md5}

    @property
    def tx(self):
        return self.key.keyfs.tx

    @cached_property
    def meta(self):
        return self.key.get()

    def file_exists(self):
        return self.tx.io_file_exists(self._filepath)

    def file_delete(self):
        return self.tx.io_file_delete(self._filepath)

    def file_md5(self):
        if self.file_exists():
            return hashlib.md5(self.file_get_content()).hexdigest()

    def file_size(self):
        return self.tx.io_file_size(self._filepath)

    def __repr__(self):
        return "<FileEntry %r>" %(self.key)

    def file_open_read(self):
        return open(self._filepath, "rb")

    def file_get_content(self):
        return self.tx.io_file_get(self._filepath)

    def file_set_content(self, content, last_modified=None, md5=None):
        assert isinstance(content, bytes)
        if last_modified != -1:
            if last_modified is None:
                last_modified = format_date_time(None)
            self.last_modified = last_modified
        #else we are called from replica thread and just write outside
        file_md5 = hashlib.md5(content).hexdigest()
        if md5 and md5 != file_md5:
            raise ValueError("md5 mismatch: %s" % self.relpath)
        self.md5 = file_md5
        self.tx.io_file_set(self._filepath, content)

    def gethttpheaders(self):
        assert self.file_exists()
        headers = {}
        headers[str("last-modified")] = str(self.last_modified)
        m = mimetypes.guess_type(self.basename)[0]
        headers[str("content-type")] = str(m)
        headers[str("content-length")] = str(self.file_size())
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

    def cache_remote_file(self):
        # we get and cache the file and some http headers from remote
        r = self.xom.httpget(self.url, allow_redirects=True)
        if r.status_code != 200:
            msg = "error %s getting %s" % (r.status_code, self.url)
            threadlog.error(msg)
            raise self.BadGateway(msg)
        log.info("reading remote: %s, target %s", r.url, self.relpath)
        content = r.raw.read()
        digest = hashlib.md5(content).hexdigest()
        filesize = len(content)
        content_size = r.headers.get("content-length")
        err = None

        if content_size and int(content_size) != filesize:
            err = ValueError(
                      "%s: got %s bytes of %r from remote, expected %s" % (
                      self.relpath, filesize, r.url, content_size))
        if not self.eggfragment and self.md5 and digest != self.md5:
            err = ValueError("%s: md5 mismatch, got %s, expected %s",
                             self.relpath, digest, self.md5)
        if err is not None:
            log.error(str(err))
            raise err

        self.file_set_content(content, r.headers.get("last-modified", None),
                              md5=digest)

    def cache_remote_file_replica(self):
        # construct master URL with param
        assert self.url, "should have private files already: %s" % self.relpath
        threadlog.info("replica doesn't have file: %s", self.relpath)
        url = self.xom.config.master_url.joinpath(self.relpath).url

        # we do a head request to master and then wait for the file
        # to arrive through the replication machinery
        r = self.xom._httpsession.head(url)
        if r.status_code != 200:
            msg = "%s: received %s from master" %(url, r.status_code)
            threadlog.error(msg)
            raise self.BadGateway(msg)
        serial = int(r.headers["X-DEVPI-SERIAL"])
        keyfs = self.key.keyfs
        keyfs.notifier.wait_tx_serial(serial)
        keyfs.restart_read_transaction()  # use latest serial
        entry = self.xom.filestore.get_file_entry(self.relpath)
        if not entry.file_exists():
            msg = "%s: did not get file after waiting" % url
            threadlog.error(msg)
            raise self.BadGateway(msg)
        return entry


def split_md5(hexdigest):
    return hexdigest[:3], hexdigest[3:16]
