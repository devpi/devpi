"""

Implementation of the database layer for PyPI Package serving and
testresult storage.

"""
import re

import json
import py
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

    def gethtml(self, url):
        """ return unicode html text from http requests
        or integer status_code if we didn't get a 200
        or we had too many redirects.
        """
        counter = 0
        while counter <= self.maxredirect:
            counter += 1
            cacheresponse = self.cache.get(url)
            if cacheresponse is not None:
                if isinstance(cacheresponse, list):
                    url = cacheresponse[1]
                    continue
                elif isinstance(cacheresponse, int):
                    # e.g. 404
                    return cacheresponse
                return cacheresponse
            response = self.httpget(url)
            if response.status_code == 200:
                self.cache.set(url, response.text)
                return response.text
            elif response.status_code in self._REDIRECTCODES:
                location = response.headers["location"]
                newurl = urlutil.joinpath(url, location)
                # we store a list because of better json-idempotence
                self.cache.set(url, [response.status_code, newurl])
                url = newurl
            else:
                self.cache.set(url, response.status_code)
                return response.status_code
        return response.status_code


class FileSystemCache:
    def __init__(self, basedir):
        self.basedir = basedir

    def get(self, url):
        path = urlutil.url2path(url)
        contentpath = self.basedir.join(path)
        try:
            with contentpath.open("rb") as f:
                return py.builtin._totext(f.read(), "utf-8")
        except py.error.ENOENT:
            pass
        metapath = contentpath + "--jsonmeta"
        try:
            with metapath.open("rb") as f:
                return json.load(f, "utf-8")
        except py.error.ENOENT:
            return None

    def set(self, url, value):
        path = urlutil.url2path(url)
        p = self.basedir.join(path)
        p.dirpath().ensure(dir=1)
        if py.builtin._isbytes(value):
            as_bytes = value
        elif py.builtin._istext(value):
            as_bytes = value.encode("utf-8")
        else:
            p = p + "--jsonmeta"
            with p.open("wb") as f:
                json.dump(value, f)
            return
        p.write(as_bytes)
