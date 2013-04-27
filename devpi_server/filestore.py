
from hashlib import md5
import py
from .types import propmapping
from logging import getLogger
log = getLogger(__name__)

class ReleaseFileStore:
    HASHDIRLEN = 2

    def __init__(self, redis, basedir):
        self.redis = redis
        self.basedir = basedir

    def maplink(self, link, refresh=False):
        entry = self.getentry_fromlink(link)
        if not entry.iscached() or refresh:
            mapping = dict(url=link.url_nofrag)
            if link.md5:
                mapping["md5"] = link.md5
            if link.eggfragment:
                mapping["eggfragment"] = link.eggfragment
            entry.set(**mapping)
        return entry

    def canonical_relpath(self, link):
        if link.eggfragment:
            m = md5(link.url.encode("utf8"))
            basename = link.eggfragment
        else:
            m = md5(link.url_nofrag.encode("utf8"))
            basename = link.basename
        return "%s/%s" %(m.hexdigest()[:self.HASHDIRLEN], basename)

    def getentry_fromlink(self, link):
        return self.getentry(self.canonical_relpath(link))

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
        entry.sethttpheaders(r.headers)
        log.info("cache-streaming remote: %s", r.url)
        target = entry.filepath
        target.dirpath().ensure(dir=1)
        def iter_and_cache():
            tmp_target = target + "-tmp"
            hash = md5()
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
            tmp_target.move(target)
            entry.set(md5=digest, size=filesize)
            log.info("finished getting remote %r", entry.url)
        return entry.gethttpheaders(), iter_and_cache()


class RelPathEntry(object):
    SITEPATH = "s:"

    _attr = set("md5 url eggfragment size last_modified "
                "content_type".split())

    def __init__(self, redis, relpath, basedir):
        self.redis = redis
        self.relpath = relpath
        self.filepath = basedir.join(self.relpath)
        self.rediskey = self.SITEPATH + self.relpath
        self._mapping = redis.hgetall(self.rediskey)

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
        self.redis.hdel(self.rediskey, "_headers")
        try:
            del self._mapping["_headers"]
        except KeyError:
            pass
        try:
            self.filepath.remove()
        except py.error.ENOENT:
            pass

    @property
    def basename(self):
        try:
            return self._mapping["basename"]
        except KeyError:
            return self.relpath.split("/")[1]

    def iscached(self):
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
        self.redis.hmset(self.rediskey, mapping)

for _ in RelPathEntry._attr:
    setattr(RelPathEntry, _, propmapping(_))
