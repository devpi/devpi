"""
Module for handling storage and proxy-streaming and caching of release files
for all indexes.

"""
from __future__ import unicode_literals
import hashlib
import mimetypes
import json
from wsgiref.handlers import format_date_time
from datetime import datetime
from time import mktime
from devpi_common.types import cached_property
from .keyfs import _nodefault
from .log import threadlog

log = threadlog

class FileStore:
    attachment_encoding = "utf-8"

    def __init__(self, keyfs):
        self.keyfs = keyfs

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
        entry = FileEntry(key)
        mapping = {"url": link.geturl_nofragment().url}
        mapping["eggfragment"] = link.eggfragment
        mapping["md5"] = link.md5
        if link.md5 != entry.md5:
            if entry.file_exists():
                log.info("replaced md5, deleting stale %s" % entry.relpath)
                entry.file_delete()
            else:
                if entry.md5:
                    log.info("replaced md5 info for %s" % entry.relpath)
        entry.set(**mapping)
        assert entry.url
        return entry

    def get_file_entry(self, relpath):
        try:
            key = self.keyfs.derive_key(relpath)
        except KeyError:
            return None
        return FileEntry(key)

    def get_proxy_file_entry(self, relpath, md5, keyname):
        try:
            key = self.keyfs.derive_key(relpath, keyname=keyname)
        except KeyError:
            raise # return None
        return FileEntry(key, md5=md5)

    def store(self, user, index, filename, content, last_modified=None):
        digest = hashlib.md5(content).hexdigest()
        key = self.keyfs.STAGEFILE(user=user, index=index,
                                   md5=digest, filename=filename)
        entry = FileEntry(key)
        entry.set_file_content(content)
        entry.set(md5=digest)
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


class FileEntry(object):
    _attr = set("md5 eggfragment last_modified "
                "url projectname version".split())

    def __init__(self, key, md5=_nodefault):
        self.key = key
        self.relpath = key.relpath
        self.basename = self.relpath.split("/")[-1]
        if md5 is not _nodefault:
            self.md5 = md5

    @cached_property
    def key_content(self):
        return self.key.get()

    def __getattr__(self, name):
        if name in self._attr:
            return self.key_content.get(name)
        raise AttributeError(name)

    @property
    def meta(self):
        meta = self.key_content.copy()
        meta.pop("content", None)
        return meta

    def file_exists(self):
        return "content" in self.key_content

    @property
    def size(self):
        content = self.get_file_content()
        if content is not None:
            return len(content)

    def __repr__(self):
        return "<FileEntry %r>" %(self.key)

    def get_file_content(self):
        return self.key_content.get("content")

    def set_file_content(self, content, last_modified=None):
        assert isinstance(content, bytes)
        self.key_content["content"] = content
        if last_modified is None:
            last_modified = http_date()
        self.set(last_modified=last_modified)
        self.key.set(self.key_content)

    def file_delete(self):
        self.key_content.pop("content", None)
        self.key.set(self.key_content)

    def gethttpheaders(self):
        assert self.file_exists()
        headers = {}
        headers[str("last-modified")] = str(self.last_modified)
        m = mimetypes.guess_type(self.basename)[0]
        headers[str("content-type")] = str(m)
        headers[str("content-length")] = str(len(self.get_file_content()))
        return headers

    def __eq__(self, other):
        return (self.relpath == getattr(other, "relpath", None) and
                self.key == other.key)

    def __hash__(self):
        return hash(self.relpath)

    def set(self, **kw):
        mapping = {}
        for name, val in kw.items():
            assert name in self._attr
            if val is not None:
                mapping[name] = "%s" % (val,)
        self.key_content.update(mapping)
        self.key.set(self.key_content)

    def delete(self, **kw):
        self.key.delete()
        self.key_content = {}

    def cache_remote_file(self, httpget):
        # we get and cache the file and some http headers from remote
        r = httpget(self.url, allow_redirects=True)
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

        self.set_file_content(content, r.headers.get("last-modified", None))
        self.set(md5=digest)

    def cache_remote_file_replica(self, xom):
        threadlog.info("replica doesn't have file: %s", self.relpath)
        url = xom.config.master_url.joinpath(self.relpath).url
        r = xom.httpget(url, allow_redirects=True)  # XXX HEAD
        if r.status_code != 200:
            threadlog.error("got %s from upstream", r.status_code)
            raise ValueError("%s: received %s from master"
                             %(url, r.status_code))
        serial = int(r.headers["X-DEVPI-SERIAL"])
        keyfs = self.key.keyfs
        keyfs.notifier.wait_tx_serial(serial)
        keyfs.restart_read_transaction()
        entry = xom.filestore.get_file_entry(self.relpath)
        if not entry.file_exists():
            threadlog.error("did not get file after waiting")
            raise ValueError("%s: did not get file after waiting" % url)
        return entry


def http_date():
    now = datetime.now()
    stamp = mktime(now.timetuple())
    return format_date_time(stamp)

