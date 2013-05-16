"""
Module for handling storage and proxy-streaming and caching of release files
for all indexes.

"""
import hashlib
import posixpath
from wsgiref.handlers import format_date_time
from datetime import datetime
from time import mktime

import py
from .types import propmapping
from .urlutil import DistURL
from logging import getLogger
log = getLogger(__name__)

class ReleaseFileStore:
    def __init__(self, redis, basedir):
        self.redis = redis
        self.basedir = basedir

    def maplink(self, link, refresh=False):
        entry = self.getentry_fromlink(link)
        mapping = {}
        if link.eggfragment and not entry.eggfragment:
            mapping["eggfragment"] = link.eggfragment
        elif link.md5 and not entry.md5:
            mapping["md5"] = link.md5
        else:
            return entry
        entry.set(**mapping)
        return entry

    def mapfile(self, filename, md5):
        relpath = "%s/%s" % (md5, filename)
        entry = self.getentry(relpath)
        entry.set(md5=md5, last_modified=http_date())
        return entry

    def getentry_fromlink(self, link):
        return self.getentry(link.torelpath())

    def getentry(self, relpath):
        return RelPathEntry(self.redis, relpath, self.basedir)

    def iterfile(self, relpath, httpget, chunksize=8192):
        entry = self.getentry(relpath)
        target = entry.filepath
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
        target = entry.filepath
        if not target.check():
            error = "not exists"
        #elif not entry.headers:
        #    error = "no metainfo"
        elif entry.size != str(target.size()):
            error = "local size %s does not match header size %s" %(
                     target.size(), entry.size)
        elif entry.md5 and target.computehash() != entry.md5:
            error = "md5 %s does not match expected %s" %(entry.md5,
                target.computehash())
        else:
            error = None
        if error is not None:
            log.error("%s: %s -- invalidating cache", target, error)
            entry.invalidate_cache()
            return None, None
        # serve previously cached file and http headers
        def iterfile():
            with target.open("rb") as f:
                while 1:
                    x = f.read(chunksize)
                    if not x:
                        break
                    yield x
        return entry.gethttpheaders(), iterfile()

    def iterfile_remote(self, entry, httpget, chunksize):
        # we get and cache the file and some http headers from remote
        r = httpget(entry.url, allow_redirects=True)
        assert r.status_code >= 0, r.status_code
        entry.sethttpheaders(r.headers)
        # XXX check if we still have the file locally
        log.info("cache-streaming remote: %s", r.url)
        target = entry.filepath
        target.dirpath().ensure(dir=1)
        def iter_and_cache():
            tmp_target = target + "-tmp"
            hash = hashlib.md5()
            # XXX if we have concurrent processes they would overwrite
            # each other
            with tmp_target.open("wb") as f:
                #log.debug("serving %d remote chunk %s" % (len(x),
                #                                         relpath))
                for x in r.iter_content(chunksize):
                    assert x
                    f.write(x)
                    hash.update(x)
                    yield x
            digest = hash.hexdigest()
            err = None
            filesize = tmp_target.size()
            if entry.size and int(entry.size) != filesize:
                err = ValueError(
                          "%s: got %s bytes of %r from remote, expected %s" % (
                          tmp_target, tmp_target.size(), r.url, entry.size))
            if entry.md5 and digest != entry.md5:
                err = ValueError("%s: md5 mismatch, got %s, expected %s",
                                 tmp_target, digest, entry.md5)
            if err is not None:
                log.error(err)
                raise err
            try:
                target.remove()
            except py.error.ENOENT:
                pass
            tmp_target.move(target)
            entry.set(md5=digest, size=filesize)
            log.info("finished getting remote %r", entry.url)
        return entry.gethttpheaders(), iter_and_cache()

    def store(self, stagename, filename, content):
        md5 = getmd5(content)
        entry = self.mapfile(filename, md5)
        entry.filepath.dirpath().ensure(dir=1)
        with entry.filepath.open("wb") as f:
            f.write(content)
        entry.set(md5=md5, size=len(content))
        return entry

def getmd5(content):
    md5 = hashlib.md5()
    md5.update(content)
    return md5.hexdigest()

class RelPathEntry(object):
    _attr = set("md5 eggfragment size last_modified content_type".split())

    def __init__(self, redis, relpath, basedir):
        self.redis = redis
        self.relpath = relpath
        self.filepath = basedir.join(self.relpath)
        if relpath.split("/", 1)[0] in ("http", "https"):
            disturl = DistURL.fromrelpath(relpath)
            self.url = disturl.url
            self.basename = disturl.basename
        else:
            self.basename = posixpath.basename(relpath)
        self.HSITEPATH = "s:" + self.relpath
        self._mapping = redis.hgetall(self.HSITEPATH)

    def gethttpheaders(self):
        headers = {"last-modified": self.last_modified,
                   "content-type": self.content_type}
        if self.size is not None:
            headers["content-length"] = str(self.size)
        return headers

    def sethttpheaders(self, headers):
        self.set(last_modified=headers["last-modified"],
                 size = headers["content-length"],
                 content_type = headers["content-type"])

    def invalidate_cache(self):
        self.redis.hdel(self.HSITEPATH, "_headers")
        try:
            del self._mapping["_headers"]
        except KeyError:
            pass
        try:
            self.filepath.remove()
        except py.error.ENOENT:
            pass

    def iscached(self):
        # compare md5 hash if exists with self.filepath
        # XXX move file store scheme to have md5 hash within the filename
        # but a filename should only contain the md5 hash if it is verified
        # i.e. we maintain an invariant that <md5>/filename has a content
        # that matches the md5 hash. It is therefore possible that a
        # entry.md5 is set, but entry.relpath
        return self.filepath.check()

    def __eq__(self, other):
        return (self.relpath == other.relpath and
                self._mapping == other._mapping)

    def set(self, **kw):
        mapping = {}
        for name, val in kw.items():
            assert name in self._attr
            if val is not None:
                mapping[name] = str(val)
        self._mapping.update(mapping)
        self.redis.hmset(self.HSITEPATH, mapping)

for _ in RelPathEntry._attr:
    setattr(RelPathEntry, _, propmapping(_))


def http_date():
    now = datetime.now()
    stamp = mktime(now.timetuple())
    return format_date_time(stamp)

