"""

Implementation of the database layer for PyPI Package serving and
testresult storage.

"""
import re
import os, sys
import py
import json
from devpi.util import url as urlutil
from devpi.util import version as verlib
from bs4 import BeautifulSoup
import posixpath
import pkg_resources


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

_releasefile_suffix_rx = re.compile(r"(\.zip|\.tar\.gz|\.tgz|\.tar\.bz2|-py[23]\.\d-.*|\.win-amd64-py[23]\.\d\..*|\.win32-py[23]\.\d\..*)$", re.IGNORECASE)

def guess_pkgname_and_version(path):
    path = os.path.basename(path)
    pkgname = re.split(r"-\d+", path, 1)[0]
    version = path[len(pkgname) + 1:]
    version = _releasefile_suffix_rx.sub("", version)
    return pkgname, version

class DistURL:
    def __init__(self, url):
        self.url = url

    def __repr__(self):
        return "<DistURL url=%r>" % (self.url, )

    def __eq__(self, other):
        return self.url == getattr(other, "url", other)

    @property
    def pkgname_and_version(self):
        return guess_pkgname_and_version(self.basename)

    @property
    def easyversion(self):
        return pkg_resources.parse_version(self.pkgname_and_version[1])

    def __cmp__(self, other):
        """ sorting as defined by UpstreamCache.getpackagelinks() """
        return cmp(self.easyversion, other.easyversion)

    def __hash__(self):
        return hash(self.url)

    def splitext(self):
        base, ext = posixpath.splitext(self.basename)
        if base.lower().endswith('.tar'):
            ext = base[-4:] + ext
            base = base[:-4]
        return base, ext

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
    ALLOWED_ARCHIVE_EXTS = ".tar.gz .tar.bz2 .tar .tgz .zip".split()

    def __init__(self, projectname):
        self.projectname = projectname
        self.releaselinks = set()
        self.scrapelinks = set()

    def parse_index(self, disturl, html, scrape=True):
        for a in BeautifulSoup(html).findAll("a"):
            newurl = disturl.makeurl(a.get("href"))
            nameversion, ext = newurl.splitext()
            projectname = re.split(r"-\d+", nameversion)[0]
            if ext in self.ALLOWED_ARCHIVE_EXTS and \
               projectname == self.projectname:
                self.releaselinks.add(newurl)
                continue
            if scrape:
                if newurl.eggfragment:
                    self.releaselinks.add(newurl)
                else:
                    for rel in a.get("rel", []):
                        if rel in ("homepage", "download"):
                            self.scrapelinks.add(newurl)

def parse_index(disturl, html, scrape=True):
    if not isinstance(disturl, DistURL):
        disturl = DistURL(disturl)
    projectname = disturl.basename or disturl.parentbasename
    parser = IndexParser(projectname)
    parser.parse_index(disturl, html, scrape=scrape)
    return parser


class HTTPCacheAdapter:
    _REDIRECTCODES = (301, 302, 303, 307)

    def __init__(self, cache, httpget=None, maxredirect=10):
        self.cache = cache
        if httpget is None:
            import requests
            def httpget(url):
                return requests.get(url, allow_redirects=False)
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
        with contentpath.open("wb") as f:
            f.write(body.encode("utf-8"))
        self.redis.hmset(self.METAPREFIX + path, dict(status_code=200))
        return FSCacheResponse(url, status_code=200, contentpath=contentpath)

    def setmeta(self, url, status_code, nextlocation=None):
        path = urlutil.url2path(url)
        mapping = dict(status_code = status_code)
        if nextlocation is not None:
            mapping["nextlocation"] = nextlocation
        self.redis.hmset(self.METAPREFIX + path, mapping)
        return self.get(url)


class ExtDB:
    def __init__(self, upstreamurl, httpcache):
        self.upstreamurl = upstreamurl
        self.httpcache = httpcache

    def getreleaselinks(self, projectname):
        url = self.upstreamurl + projectname + "/"
        print "visiting index", url
        response = self.httpcache.get(url)
        assert response.status_code == 200
        result = parse_index(response.url, response.text)
        for scrapeurl in result.scrapelinks:
            print "visiting scrapeurl", scrapeurl
            response = self.httpcache.get(scrapeurl.url)
            print "scrapeurl", scrapeurl, response.status_code
            if response.status_code == 200:
                result.parse_index(DistURL(response.url), response.text)
        releaselinks = list(result.releaselinks)
        releaselinks.sort(reverse=True)
        return releaselinks

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
    http = HTTPCacheAdapter(fscache)
    extdb = ExtDB("https://pypi.python.org/simple/", http)
    import time
    now = time.time()
    for name in args.projectname:
        links = extdb.getreleaselinks(name)
        for link in links:
            print link
    elapsed = time.time() - now
    print "retrieval took %.3f seconds" % elapsed
