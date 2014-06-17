"""
Module for handling storage and proxy-streaming and caching of release files
for all indexes.

"""
from __future__ import unicode_literals
import os
import hashlib
import mimetypes
import json
from wsgiref.handlers import format_date_time
from datetime import datetime
from time import mktime
from devpi_common.types import cached_property
from .keyfs import _nodefault, get_write_file_ensure_dir
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
            md5a, md5b = link.md5[:3], link.md5[3:]
            key = self.keyfs.PYPISTAGEFILE(user="root", index="pypi",
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

    def get_proxy_file_entry(self, relpath, md5, keyname):
        try:
            key = self.keyfs.derive_key(relpath, keyname=keyname)
        except KeyError:
            raise # return None
        return FileEntry(self.xom, key, md5=md5)

    def store(self, user, index, filename, content, last_modified=None):
        digest = hashlib.md5(content).hexdigest()
        key = self.keyfs.STAGEFILE(user=user, index=index,
                                   md5=digest, filename=filename)
        entry = FileEntry(self.xom, key)
        entry.file_set_content(content, md5=digest)
        return entry

    def add_attachment(self, md5, type, data):
        assert type in ("toxresult",)
        with self.keyfs.ATTACHMENTS.update() as attachments:
            l = attachments.setdefault(md5, {}).setdefault(type, [])
            num = str(len(l))
            key = self.keyfs.ATTACHMENT(type=type, md5=md5, num=num)
            key.set(data.encode(self.attachment_encoding))
            l.append(num)
        return num

    def get_attachment(self, md5, type, num):
        data = self.keyfs.ATTACHMENT(type=type, md5=md5, num=num).get()
        return data.decode(self.attachment_encoding)

    def iter_attachments(self, md5, type):
        attachments = self.keyfs.ATTACHMENTS.get()
        l = attachments.get(md5, {}).get(type, [])
        for num in l:
            a = self.keyfs.ATTACHMENT(num=num, type=type, md5=md5).get()
            yield json.loads(a.decode(self.attachment_encoding))

    def iter_attachment_types(self, md5):
        attachments = self.keyfs.ATTACHMENTS.get()
        return list(attachments.get(md5, {}))


def metaprop(name):
    def fget(self):
        if self.meta is not None:
            return self.meta.get(name)
    def fset(self, val):
        self.meta[name] = val
        self.key.set(self.meta)
    return property(fget, fset)


class FileEntry(object):
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

    @cached_property
    def meta(self):
        return self.key.get()

    def file_exists(self):
        return os.path.exists(self._filepath)

    def file_delete(self, raising=True):
        # XXX if a transaction is ongoing, register the remove with it
        # (requires more support/logic from Transaction)
        try:
            os.remove(self._filepath)
        except (OSError, IOError):
            if raising:
                raise
        else:
            threadlog.debug("deleted file: %s", self._filepath)

    def file_md5(self):
        if self.file_exists():
            return hashlib.md5(self.file_get_content()).hexdigest()

    def file_size(self):
        try:
            return os.path.getsize(self._filepath)
        except OSError:
            return None

    def __repr__(self):
        return "<FileEntry %r>" %(self.key)

    def file_open_read(self):
        return open(self._filepath, "rb")

    def file_get_content(self):
        with self.file_open_read() as f:
            return f.read()

    def file_set_content(self, content, last_modified=None, md5=None):
        assert isinstance(content, bytes)
        if last_modified != -1:
            if last_modified is None:
                last_modified = http_date()
            self.last_modified = last_modified
        #else we are called from replica thread and just write out
        if md5 is not None:
            self.md5 = md5
        if self.md5 and hashlib.md5(content).hexdigest() != self.md5:
            raise ValueError("md5 mismatch: %s" % self.relpath)
        with get_write_file_ensure_dir(self._filepath) as f:
            f.write(content)

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
        self.file_delete(raising=False)

    def cache_remote_file(self):
        # we get and cache the file and some http headers from remote
        r = self.xom.httpget(self.url, allow_redirects=True)
        assert r.status_code >= 0, r.status_code
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
        r = self.xom._httpsession.head(url)
        if r.status_code != 200:
            threadlog.error("got %s from upstream", r.status_code)
            raise ValueError("%s: received %s from master"
                             %(url, r.status_code))
        serial = int(r.headers["X-DEVPI-SERIAL"])
        keyfs = self.key.keyfs
        keyfs.notifier.wait_tx_serial(serial)
        keyfs.restart_read_transaction()
        entry = self.xom.filestore.get_file_entry(self.relpath)
        if not entry.file_exists():
            threadlog.error("did not get file after waiting")
            raise ValueError("%s: did not get file after waiting" %
            url)
        return entry


def http_date():
    now = datetime.now()
    stamp = mktime(now.timetuple())
    return format_date_time(stamp)

