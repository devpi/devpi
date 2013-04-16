"""

Implementation of the database layer for PyPI Package serving and
testresult storage.

"""
import re
import os, sys
import py
import requests
import json
from devpi.util import url as urlutil
from bs4 import BeautifulSoup
import posixpath


def cached_property(f):
    """returns a cached property that is calculated by function f"""
    def get(self):
        try:
            return self._property_cache[f]
        except AttributeError:
            self._property_cache = {}
            x = self._property_cache[f] = f(self)
            return x
        except KeyError:
            x = self._property_cache[f] = f(self)
            return x
    return property(get)

class DistURL:
    def __init__(self, url):
        self.url = url

    def __repr__(self):
        return "<DistURL url=%r>" % (self.url, )

    def __eq__(self, other):
        return self.url == getattr(other, "url", other)

    def __hash__(self):
        return hash(self.url)

    @cached_property
    def _parsed(self):
        return urlutil.urlparse(self.url)

    @property
    def basename(self):
        return posixpath.basename(self._parsed.path)

    @property
    def parentbasename(self):
        return posixpath.basename(posixpath.dirname(self._parsed.path))

    @property
    def eggfragment(self):
        frag = self._parsed.fragment
        if frag.startswith("egg="):
            return frag[4:]

    @property
    def md5(self):
        val = self._parsed.fragment
        if val.startswith("md5="):
            return val[4:]

    def makeurl(self, url):
        newurl = urlutil.joinpath(self.url, url)
        return DistURL(newurl)

class IndexParser:
    def __init__(self, projectname):
        self.projectname = projectname
        self.releaselinks = []
        self.scrapelinks = []

    def parse_index(self, disturl, html, scrape=True):
        for a in BeautifulSoup(html).findAll("a"):
            newurl = disturl.makeurl(a.get("href"))
            projectname = re.split(r"-\d+", newurl.basename)[0]
            if projectname == self.projectname:
                self.releaselinks.append(newurl)
                continue
            if scrape:
                if newurl.eggfragment:
                    self.releaselinks.append(newurl)
                else:
                    for rel in a.get("rel", []):
                        if rel in ("homepage", "download"):
                            self.scrapelinks.append(newurl)

def parse_index(disturl, html):
    if not isinstance(disturl, DistURL):
        disturl = DistURL(disturl)
    projectname = disturl.basename or disturl.parentbasename
    parser = IndexParser(projectname)
    parser.parse_index(disturl, html)
    return parser


class HTTPCacheAdapter:
    _REDIRECTCODES = (301, 302, 303, 307)

    def __init__(self, cache, httpget=None, maxredirect=10):
        self.cache = cache
        self.httpget = httpget
        self.maxredirect = maxredirect
        assert self.maxredirect >= 0

    def get(self, url):
        """ return unicode html text from http requests
        or integer status_code if we didn't get a 200
        or we had too many redirects.
        """
        counter = 0
        while counter <= self.maxredirect:
            counter += 1
            cacheresponse = self.cache.get(url)
            if cacheresponse is not None:
                if cacheresponse.status_code in self._REDIRECTCODES:
                    url = cacheresponse.nextlocation
                    continue
                return cacheresponse
            response = self.httpget(url)
            if response.status_code == 200:
                return self.cache.setbody(url, response.text)
            elif response.status_code in self._REDIRECTCODES:
                location = response.headers["location"]
                newurl = urlutil.joinpath(url, location)
                # we store a list because of better json-idempotence
                self.cache.setmeta(url, status_code=response.status_code,
                                   nextlocation=newurl)
                url = newurl
            else:
                return self.cache.setmeta(url, status_code=response.status_code)
        return response.status_code


class FSCacheResponse(object):
    def __init__(self, url, status_code, nextlocation=None, contentpath=None):
        self.url = url
        self.status_code = status_code
        self.nextlocation = nextlocation
        self.contentpath = contentpath

    @property
    def text(self):
        try:
            with self.contentpath.open("rb") as f:
                return f.read().decode("utf-8")
        except (AttributeError, py.error.ENOENT):
            return None


class FSCache:

    METAPREFIX = "cache:"

    def __init__(self, basedir, redis):
        self.basedir = basedir
        self.redis = redis

    def get(self, url):
        path = urlutil.url2path(url)
        mapping = self.redis.hgetall(self.METAPREFIX + path)
        if not mapping:
            return None
        #print "redis-got", mapping
        contentpath = self.basedir.join(path + "--body")
        return FSCacheResponse(url=url,
                               status_code=int(mapping['status_code']),
                               nextlocation=mapping.get("nextlocation"),
                               contentpath=contentpath)

    def setbody(self, url, body):
        path = urlutil.url2path(url)
        contentpath = self.basedir.join(path + "--body")
        contentpath.dirpath().ensure(dir=1)
        contentpath.write(body.encode("utf-8"))
        self.redis.hmset(self.METAPREFIX + path, dict(status_code=200))
        return FSCacheResponse(url, status_code=200, contentpath=contentpath)

    def setmeta(self, url, status_code, nextlocation=None):
        path = urlutil.url2path(url)
        mapping = dict(status_code = status_code)
        if nextlocation is not None:
            mapping["nextlocation"] = nextlocation
        self.redis.hmset(self.METAPREFIX + path, mapping)
        return self.get(url)

def parse_args(argv):
    import argparse
    argv = map(str, argv)
    parser = argparse.ArgumentParser(prog=argv[0])

    parser.add_argument("--data", metavar="DIR", type=str, dest="datadir",
        default="~/.devpi/data",
        help="data directory, where database and packages are stored",
    )

    parser.add_argument("projectname", type=str, nargs="+",
        help="projectname for which index is looked up at pypi.python.org",
    )
    return parser.parse_args(argv[1:])

def main(argv=None):
    import redis
    client = redis.StrictRedis()
    if argv is None:
        argv = sys.argv
    args = parse_args(argv)

    from devpi_server.extpypi import FSCache, HTTPCacheAdapter
    target = py.path.local(os.path.expanduser(args.datadir))
    fscache = FSCache(target.join("httpcache"), client)
    def httpget(url):
        return requests.get(url, allow_redirects=False)
    http = HTTPCacheAdapter(fscache, httpget)
    from devpi_server.extpypi import parse_index
    import time
    now = time.time()
    for name in args.projectname:
        url = "http://localhost:3141/~hpk42/dev10/simple/%s" % name
        url = "https://pypi.python.org/simple/%s" % name
        print "retrieving index", url
        r = http.get(url)
        result = parse_index(r.url, r.text)
        print "%d releaselinks %d scrapelinks" %(len(result.releaselinks),
                                                 len(result.scrapelinks))
        #for x in result.releaselinks:
        #    print "  ", x.basename, x.md5
        #print result.scrapelinks
    elapsed = time.time() - now
    print "retrieval took %.3f seconds" % elapsed
