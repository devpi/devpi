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
from devpi_server.plugin import hookimpl


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

    def geturl_nofragment(self):
        """ return url without fragment """
        scheme, netloc, url, params, query, ofragment = self._parsed
        return DistURL(urlutil.urlunsplit((scheme, netloc, url, query, "")))

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
        self.basename2link = {}
        self.crawllinks = set()

    def _mergelink_ifbetter(self, newurl):
        entry = self.basename2link.get(newurl.basename)
        if entry is None or (not entry.md5 and newurl.md5):
            self.basename2link[newurl.basename] = newurl

    @property
    def releaselinks(self):
        """ return sorted releaselinks list """
        l = list(self.basename2link.values())
        l.sort(reverse=True)
        return l

    def parse_index(self, disturl, html, scrape=True):
        for a in BeautifulSoup(html).findAll("a"):
            newurl = disturl.makeurl(a.get("href"))
            nameversion, ext = newurl.splitext()
            projectname = re.split(r"-\d+", nameversion)[0]
            if ext in self.ALLOWED_ARCHIVE_EXTS and \
               projectname == self.projectname:
                self._mergelink_ifbetter(newurl)
                continue
            if scrape:
                if newurl.eggfragment:
                    self.basename2link[newurl] = newurl
                else:
                    for rel in a.get("rel", []):
                        if rel in ("homepage", "download"):
                            self.crawllinks.add(newurl)

def parse_index(disturl, html, scrape=True):
    if not isinstance(disturl, DistURL):
        disturl = DistURL(disturl)
    projectname = disturl.basename or disturl.parentbasename
    parser = IndexParser(projectname)
    parser.parse_index(disturl, html, scrape=scrape)
    return parser


class HTTPCacheAdapter:
    _REDIRECTCODES = (301, 302, 303, 307)

    def __init__(self, cache, httpget, maxredirect=10):
        assert maxredirect >= 0
        self.cache = cache
        self.httpget = httpget
        self.maxredirect = maxredirect

    def get(self, url, refresh=False):
        """ return unicode html text from http requests
        or integer status_code if we didn't get a 200
        or we had too many redirects.
        """
        counter = 0
        while counter <= self.maxredirect:
            counter += 1
            if not refresh:
                cacheresponse = self.cache.get(url)
                if cacheresponse is not None:
                    if cacheresponse.status_code in self._REDIRECTCODES:
                        url = cacheresponse.nextlocation
                        continue
                    return cacheresponse
            # we create an empty cache entry so that
            # the concurrently running changelogscanner can update
            # the entry already if it runs in-between
            response = self.httpget(url)
            if not refresh:
                cached_response = self.cache.get(url)
                if cached_response is not None:
                    # changelog already updated
                    return cached_response
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

class XMLProxy:
    def __init__(self, url):
        import xmlrpclib
        self._proxy = xmlrpclib.ServerProxy(url)

    def changelog_last_serial(self):
        return self._proxy.changelog_last_serial()

    def changelog_since_serial(self, serial):
        return self._proxy.changelog_since_serial(serial)


class ExtDB:
    def __init__(self, url_base, httpcache):
        self.url_base = url_base
        self.url_simple = url_base + "simple/"
        self.url_xmlrpc = url_base + "pypi"
        self.httpcache = httpcache
        self.redis = httpcache.cache.redis
        self.PROJECTS = "projects:" + url_base

    def iscontained(self, projectname):
        return self.redis.hexists(self.PROJECTS, projectname)

    def getprojectnames(self):
        keyvals = self.redis.hgetall(self.PROJECTS)
        return set([key for key,val in keyvals.items() if val])

    def getreleaselinks(self, projectname, refresh=False):
        if not refresh:
            res = self.redis.hget(self.PROJECTS, projectname)
            if res:
                dumplinks = json.loads(res)
                return [DistURL(x) for x in dumplinks]
        # mark it as being accessed if it hasn't already
        self.redis.hsetnx(self.PROJECTS, projectname, "")

        url = self.url_simple + projectname + "/"
        print "visiting index", url
        response = self.httpcache.get(url, refresh=refresh)
        if response.status_code != 200:
            return None
        assert response.text is not None, response.text
        result = parse_index(response.url, response.text)
        for crawlurl in result.crawllinks:
            print "visiting crawlurl", crawlurl
            response = self.httpcache.get(crawlurl.url, refresh=refresh)
            print "crawlurl", crawlurl, response.status_code
            if response.status_code == 200:
                result.parse_index(DistURL(response.url), response.text)
        releaselinks = list(result.releaselinks)
        releaselinks.sort(reverse=True)
        dumplist = [x.url for x in releaselinks]
        self.redis.hset(self.PROJECTS, projectname, json.dumps(dumplist))
        return releaselinks

class RefreshManager:
    def __init__(self, extdb, xom):
        self.extdb = extdb
        self.xom = xom
        self.redis = extdb.httpcache.cache.redis
        self.PYPISERIAL = "pypiserial:" + extdb.url_base
        self.INVALIDSET = "invalid:" + extdb.url_base

    def spawned_pypichanges(self, proxy, proxysleep):
        redis = self.redis
        current_serial = redis.get(self.PYPISERIAL)
        if current_serial is None:
            current_serial = proxy.changelog_last_serial()
            redis.set(self.PYPISERIAL, current_serial)
        else:
            current_serial = int(current_serial)
        while 1:
            changelog = proxy.changelog_since_serial(current_serial)
            if changelog:
                self.mark_refresh(changelog)
                current_serial += len(changelog)
                redis.set(self.PYPISERIAL, current_serial)
            proxysleep()

    def mark_refresh(self, changelog):
        projectnames = set([x[0] for x in changelog])
        redis = self.redis
        for name in projectnames:
            if self.extdb.iscontained(name):
                redis.sadd(self.INVALIDSET, name)

    def spawned_refreshprojects(self, invalidationsleep):
        """ Invalidation task for re-freshing project indexes. """
        # note that this is written such that it could
        # be killed and restarted anytime without loosing
        # refreshing tasks (but possibly performing them twice)
        while 1:
            names = self.redis.smembers(self.INVALIDSET)
            if not names:
                invalidationsleep()
                continue
            for name in names:
                self.extdb.getreleaselinks(name, refresh=True)
                self.redis.srem(self.INVALIDSET, name)

@hookimpl()
def server_addoptions(parser):
    parser.add_argument("--pypilookup", metavar="NAME", type=str,
            default=None,
            help="lookup specified project on pypi upstream server")

    parser.add_argument("--refresh", action="store_true",
            default=None,
            help="enabled resfreshing")

    parser.add_argument("--url_base", metavar="url", type=str,
            default="https://pypi.python.org/",
            help="base url of main remote pypi server (without simple/)")


@hookimpl(tryfirst=True)
def server_mainloop(xom):
    """ entry point for showing release links via --pypilookup """
    projectname = xom.config.args.pypilookup
    if projectname is None:
        return

    extdb = xom.hook.resource_extdb(xom=xom)
    now = py.std.time.time()
    links = extdb.getreleaselinks(projectname=projectname,
                                  refresh=xom.config.args.refresh)
    for link in links:
        print link.url
    elapsed = py.std.time.time() - now
    print "retrieval took %.3f seconds" % elapsed
    return True

@hookimpl()
def resource_extdb(xom):
    httpcache = xom.hook.resource_httpcache(xom=xom)
    extdb = ExtDB(xom.config.args.url_base, httpcache)
    #extdb.scanner = pypichangescan(config.args.url_base+"pypi", httpcache)
    return extdb


@hookimpl()
def resource_httpcache(xom):
    redis = xom.hook.resource_redis(xom=xom)
    target = py.path.local(os.path.expanduser(xom.config.args.datadir))
    fscache = FSCache(target.join("httpcache"), redis)
    httpget = xom.hook.resource_httpget(xom=xom)
    return HTTPCacheAdapter(fscache, httpget)

@hookimpl()
def resource_httpget(xom):
    import requests
    def httpget(url):
        return requests.get(url, allow_redirects=False)
    return httpget
