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

    def getfile(self, relpath, httpget, chunksize=8192*16):
        entry = self.getentry(relpath)
        if not entry.PATHENTRY.exists():
            return None, None
        cached = entry.iscached() and not entry.eggfragment
        if cached:
            return entry.gethttpheaders(), entry.FILE.get()
        else:
            return self.getfile_remote(entry, httpget)

    def getfile_remote(self, entry, httpget):
        # we get and cache the file and some http headers from remote
        r = httpget(entry.url, allow_redirects=True)
        assert r.status_code >= 0, r.status_code
        log.info("cache-streaming: %s, target %s", r.url, entry.FILE.relpath)
        content = r.raw.read()
        digest = hashlib.md5(content).hexdigest()
        filesize = len(content)
        err = None
        entry.sethttpheaders(r.headers)
        if entry.size and int(entry.size) != filesize:
            err = ValueError(
                      "%s: got %s bytes of %r from remote, expected %s" % (
                      entry.FILE.relpath, filesize, r.url, entry.size))
        if not entry.eggfragment and entry.md5 and digest != entry.md5:
            err = ValueError("%s: md5 mismatch, got %s, expected %s",
                             entry.FILE.relpath, digest, entry.md5)
        if err is not None:
            log.error(err)
            raise err
        entry.FILE.set(content)
        entry.set(md5=digest, size=filesize)
        return entry.gethttpheaders(), content

    def store(self, user, index, filename, content, last_modified=None):
        digest = hashlib.md5(content).hexdigest()
        key = self.keyfs.STAGEFILE(user=user, index=index,
                                   md5=digest, filename=filename)
        key.set(content)
        log.info("setting stagefile %s" % key.relpath)
        entry = self.getentry(key.relpath)
        if last_modified is None:
            last_modified = http_date()
        entry.set(md5=digest, size=len(content), last_modified=last_modified)
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

