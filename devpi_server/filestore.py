
from hashlib import md5
import json
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
        if not entry or refresh:
            mapping = dict(url=link.url_nofrag)
            if link.md5:
                mapping["md5"] = link.md5
            if link.eggfragment:
                mapping["eggfragment"] = link.eggfragment
            entry.set(mapping)
        return entry

    def canonical_relpath(self, link):
        if link.eggfragment:
            m = md5(link.url)
            basename = link.eggfragment
        else:
            m = md5(link.url_nofrag)
            basename = link.basename
        return "%s/%s" %(m.hexdigest()[:self.HASHDIRLEN], basename)

    def getentry_fromlink(self, link):
        return self.getentry(self.canonical_relpath(link))

    def getentry(self, relpath):
        return RelPathEntry(self.redis, relpath, self.basedir)

    def iterfile(self, relpath, httpget, chunksize=8192):
        entry = self.getentry(relpath)
        target = entry.filepath
        if entry.headers is None or entry.eggfragment:
            # we get and cache the file and some http headers from remote
            r = httpget(entry.url, allow_redirects=True)
            headers = {}
            # we assume these headers to be present and forward them
            headers["last-modified"] = r.headers["last-modified"]
            headers["content-length"] = r.headers["content-length"]
            headers["content-type"] = r.headers["content-type"]
            log.info("cache-streaming remote: %s headers: %r" %(
                        r.url, headers))
            target.dirpath().ensure(dir=1)
            def iter_and_cache():
                tmp_target = target + "-tmp"
                hash = md5()
                with tmp_target.open("wb") as f:
                    #log.debug("serving %d remote chunk %s" % (len(x),
                    #                                         relpath))
                    for x in r.iter_content(chunksize):
                        assert x
                        f.write(x)
                        hash.update(x)
                        yield x
                tmp_target.move(target)
                hexdigest = hash.hexdigest()
                entry.set(dict(md5=hexdigest,
                          _headers=json.dumps(headers)))
                log.info("finished getting remote %r", entry.url)
            iterable = iter_and_cache()
        else:
            # serve previously cached file and http headers
            headers = entry.headers
            def iterfile():
                hash = md5()
                with target.open("rb") as f:
                    while 1:
                        x = f.read(chunksize)
                        if not x:
                            break
                        #log.debug("serving chunk %s" % relpath)
                        hash.update(x)
                        yield x
                if hash.hexdigest() != entry.md5:
                    raise ValueError("stored md5 %r does not match real %r" %(
                                     entry.md5, hash.hexdigest() ))
            iterable = iterfile()
        #entry.incdownloads()
        log.info("starting file iteration: %s (size %s)" % (
                entry.relpath, headers["content-length"]))
        return headers, iterable


class RelPathEntry(object):
    SITEPATH = "s:"

    def __init__(self, redis, relpath, basedir):
        self.redis = redis
        self.relpath = relpath
        self.filepath = basedir.join(self.relpath)
        self._mapping = redis.hgetall(self.rediskey)

    @property
    def rediskey(self):
        return self.SITEPATH + self.relpath

    @property
    def basename(self):
        try:
            return self._mapping["basename"]
        except KeyError:
            return self.relpath.split("/")[1]

    def __nonzero__(self):
        return bool(self._mapping)

    def __eq__(self, other):
        return (self.relpath == other.relpath and
                self._mapping == other._mapping)

    url = propmapping("url")
    md5 = propmapping("md5")
    _headers = propmapping("_headers")
    eggfragment = propmapping("eggfragment")  # for #egg= links
    #download = propmapping("download")

    @property
    def headers(self):
        if self._headers is not None:
            return json.loads(self._headers)

    def set(self, mapping):
        self.redis.hmset(self.rediskey, mapping)
        self._mapping.update(mapping)
