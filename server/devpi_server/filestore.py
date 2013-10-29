"""
Module for handling storage and proxy-streaming and caching of release files
for all indexes.

"""
from __future__ import unicode_literals
import hashlib
import posixpath
import os
import sys
import json
from wsgiref.handlers import format_date_time
from datetime import datetime
from time import mktime

import py
from devpi_common.types import propmapping, ensure_unicode

from logging import getLogger
log = getLogger(__name__)

class FileStore:
    attachment_encoding = "utf-8"

    def __init__(self, keyfs):
        self.keyfs = keyfs

    def maplink(self, link, refresh=False):
        if link.md5:
            key = self.keyfs.STAGEFILE(user="root", index="pypi",
                                       md5=link.md5 or "unknown_md5",
                                       filename=link.basename)
        else:
            key = self.keyfs.PYPIFILE_NOMD5(user="root", index="pypi",
                   relpath=link.torelpath())
        entry = self.getentry(key.relpath)
        mapping = {"url": link.geturl_nofragment().url}
        mapping["eggfragment"] = link.eggfragment
        mapping["md5"] = link.md5
        if link.md5 != entry.md5:
            if entry.FILE.exists():
                log.info("replaced md5, deleting stale %s" % entry.relpath)
                entry.FILE.delete()
            else:
                if entry.md5:
                    log.info("replaced md5 info for %s" % entry.relpath)
        entry.set(**mapping)
        assert entry.url
        return entry

    def getentry(self, relpath):
        return RelPathEntry(self.keyfs, relpath)

    def iterfile(self, relpath, httpget, chunksize=8192*16):
        entry = self.getentry(relpath)
        if not entry.PATHENTRY.exists():
            return None, None
        cached = entry.iscached() and not entry.eggfragment
        if cached:
            headers, iterable = self.iterfile_local(entry, chunksize)
            if iterable is None:
                cached = False
        if not cached:
            headers, iterable = self.iterfile_remote(entry, httpget, chunksize)
        #entry.incdownloads()
        log.info("starting file iteration: %s (size %s)" % (
                entry.relpath, entry.size or "unknown"))
        return headers, iterable

    def iterfile_local(self, entry, chunksize):
        error = None
        content = entry.FILE.get()
        if entry.size and int(entry.size) != len(content):
            error = "local size %s does not match header size %s" %(
                     len(content), entry.size)
        else:
            if entry.md5:
                md5 = getmd5(content)
                if entry.md5 != md5:
                    error = "got md5 %s expected %s" %(md5, entry.md5)
        if error is not None:
            log.error("%s: %s -- invalidating cache", entry.FILE.relpath, error)
            entry.invalidate_cache()
            return None, None
        # serve previously cached file and http headers
        def iterfile():
            yield content
        return entry.gethttpheaders(), iterfile()

    def iterfile_remote(self, entry, httpget, chunksize):
        # we get and cache the file and some http headers from remote
        r = httpget(entry.url, allow_redirects=True)
        assert r.status_code >= 0, r.status_code
        entry.sethttpheaders(r.headers)
        # XXX check if we still have the file locally
        log.info("cache-streaming: %s, target %s", r.url, entry.FILE.relpath)
        def iter_and_cache():
            hash = hashlib.md5()
            with self.keyfs.tempfile(entry.basename) as tempfile:
                while 1:
                    x = r.raw.read(chunksize)
                    if not x:
                        break
                    tempfile.write(x)
                    hash.update(x)
                    yield x
            digest = hash.hexdigest()
            err = None
            filesize = os.stat(tempfile.name).st_size
            if entry.size and int(entry.size) != filesize:
                err = ValueError(
                          "%s: got %s bytes of %r from remote, expected %s" % (
                          tempfile.name, filesize, r.url, entry.size))
            if not entry.eggfragment and entry.md5 and digest != entry.md5:
                err = ValueError("%s: md5 mismatch, got %s, expected %s",
                                 tempfile.name, digest, entry.md5)
            if err is not None:
                log.error(err)
                raise err
            tempfile.key.move(entry.FILE)
            entry.set(md5=digest, size=filesize)
            log.info("finished getting remote %r", entry.url)
        return entry.gethttpheaders(), iter_and_cache()

    def store(self, user, index, filename, content, last_modified=None):
        return self.store_file(user, index, filename, py.io.BytesIO(content),
                               last_modified=last_modified)

    def store_file(self, user, index, filename, fil, last_modified=None,
                   chunksize=524288):
        hash = hashlib.md5()
        with self.keyfs.tempfile() as w:
            size = 0
            while 1:
                s = fil.read(chunksize)
                if not s:
                    break
                hash.update(s)
                size += len(s)
                w.write(s)

        digest = hash.hexdigest()
        key = self.keyfs.STAGEFILE(user=user, index=index,
                                   md5=digest, filename=filename)
        self.keyfs._rename(w.key.relpath, key.relpath)
        entry = self.getentry(key.relpath)
        if last_modified is None:
            last_modified = http_date()
        entry.set(md5=digest, size=size, last_modified=last_modified)
        return entry

    def add_attachment(self, md5, type, data):
        assert type in ("toxresult",)
        # XXX thread safety
        num = len(self.keyfs.ATTACHMENT.listnames("num",
                                                  type=type,
                                                  md5=md5))
        num = str(num)
        key = self.keyfs.ATTACHMENT(type=type, md5=md5, num=num)
        key.set(data.encode(self.attachment_encoding))
        return num

    def get_attachment(self, md5, type, num):
        data = self.keyfs.ATTACHMENT(type=type, md5=md5, num=num).get()
        return data.decode(self.attachment_encoding)

    def iter_attachments(self, md5, type):
        nums = self.keyfs.ATTACHMENT.listnames("num", type=type, md5=md5)
        for num in range(len(nums)):
            a = self.keyfs.ATTACHMENT(num=str(num), type=type, md5=md5).get()
            yield json.loads(a.decode(self.attachment_encoding))

    def iter_attachment_types(self, md5):
        return self.keyfs.ATTACHMENT.listnames("type", md5=md5, num="0")


def getmd5(content):
    md5 = hashlib.md5()
    md5.update(content)
    return md5.hexdigest()

class RelPathEntry(object):
    _attr = set("md5 eggfragment size last_modified content_type url".split())

    def __init__(self, keyfs, relpath):
        self.keyfs = keyfs
        self.relpath = relpath
        self.FILE = keyfs.FILEPATH(relpath=relpath)
        self.basename = posixpath.basename(relpath)
        self.PATHENTRY = keyfs.PATHENTRY(relpath=relpath)
        #log.debug("self.PATHENTRY %s", self.PATHENTRY.relpath)
        #log.debug("self.FILE %s", self.FILE)
        self._mapping = self.PATHENTRY.get()

    @property
    def filepath(self):
        return self.FILE.filepath

    def __repr__(self):
        return "<RelPathEntry %r>" %(self.relpath)

    def gethttpheaders(self):
        headers = {}
        if self.last_modified:
            headers["last-modified"] = self.last_modified
        headers["content-type"] = self.content_type
        if self.size is not None:
            headers["content-length"] = str(self.size)
        return headers

    def sethttpheaders(self, headers):
        self.set(content_type = headers.get("content-type"),
                 size = headers.get("content-length"),
                 last_modified = headers.get("last-modified"))

    def exists(self):
        return bool(self._mapping)

    def invalidate_cache(self):
        try:
            del self._mapping["_headers"]
        except KeyError:
            pass
        else:
            self.PATHENTRY.set(self._mapping)
        self.FILE.delete()

    def iscached(self):
        # compare md5 hash if exists with self.filepath
        # XXX move file store scheme to have md5 hash within the filename
        # but a filename should only contain the md5 hash if it is verified
        # i.e. we maintain an invariant that <md5>/filename has a content
        # that matches the md5 hash. It is therefore possible that a
        # entry.md5 is set, but entry.relpath
        return self.FILE.exists()

    def __eq__(self, other):
        return (self.relpath == getattr(other, "relpath", None) and
                self._mapping == other._mapping)

    def __hash__(self):
        return hash(self.relpath)

    def set(self, **kw):
        mapping = {}
        for name, val in kw.items():
            assert name in self._attr
            if val is not None:
                mapping[name] = "%s" % (val,)
        self._mapping.update(mapping)
        self.PATHENTRY.set(self._mapping)

for _ in RelPathEntry._attr:
    if sys.version_info < (3,0):
        _ = _.encode("ascii")  # py2 needs str (bytes)
    setattr(RelPathEntry, _, propmapping(_, convert=ensure_unicode))

def http_date():
    now = datetime.now()
    stamp = mktime(now.timetuple())
    return format_date_time(stamp)

