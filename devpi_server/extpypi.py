"""

Implementation of the database layer for PyPI Package serving and
testresult storage.

"""
import re
import os, sys
import py
import json
from devpi.util import url as urlutil
from bs4 import BeautifulSoup
import posixpath
import pkg_resources
from devpi_server.plugin import hookimpl
from hashlib import md5
import logging
log = logging.getLogger(__name__)

import json

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
    def url_nofrag(self):
        return self.geturl_nofragment().url

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


class HTMLCache:
    def __init__(self, redis, httpget, maxredirect=10):
        assert maxredirect >= 0
        self.redis = redis
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
            cacheresponse = self.gethtmlcache(url)
            if refresh or not cacheresponse:
                response = self.httpget(url, allow_redirects=False)
                cacheresponse.setnewreponse(response)
            url = cacheresponse.nextlocation
            if url is not None:
                continue
            return cacheresponse
        return cacheresponse.status_code

    def gethtmlcache(self, url):
        rediskey = "htmlcache:" + url
        return HTMLCacheResponse(self.redis, rediskey, url)

def propmapping(name, type=None):
    if type is None:
        def fget(self):
            return self._mapping.get(name)
    else:
        def fget(self):
            x = self._mapping.get(name)
            if x is not None:
                x = type(x)
            return x
    fget.__name__ = name
    return property(fget)

class HTMLCacheResponse(object):
    _REDIRECTCODES = (301, 302, 303, 307)

    def __init__(self, redis, rediskey, url):
        self.url = url
        self.redis = redis
        self.rediskey = rediskey
        self._mapping = redis.hgetall(rediskey)

    def __nonzero__(self):
        return bool(self._mapping)

    status_code = propmapping("status_code", int)
    nextlocation = propmapping("nextlocation")
    content = propmapping("content")

    @property
    def text(self):
        """ return unicode content or None if it doesn't exist. """
        content = self.content
        if content is not None:
            return content.decode("utf8")

    def setnewreponse(self, response):
        mapping = dict(status_code = response.status_code)
        if response.status_code in self._REDIRECTCODES:
            mapping["nextlocation"] = urlutil.joinpath(self.url,
                                                  response.headers["location"])
        elif response.status_code == 200:
            mapping["content"] = response.text.encode("utf8")
        elif response.status_code < 0:
            # fatal response (no network, DNS problems etc) -> don't cache
            return
        self.redis.hmset(self.rediskey, mapping)
        self._mapping = mapping


class XMLProxy:
    def __init__(self, url):
        import xmlrpclib
        self._proxy = xmlrpclib.ServerProxy(url)

    def changelog_last_serial(self):
        return self._proxy.changelog_last_serial()

    def changelog_since_serial(self, serial):
        return self._proxy.changelog_since_serial(serial)


class ExtDB:
    def __init__(self, url_base, htmlcache, releasefilestore):
        self.url_base = url_base
        self.url_simple = url_base + "simple/"
        self.url_xmlrpc = url_base + "pypi"
        self.htmlcache = htmlcache
        self.redis = htmlcache.redis
        self.PROJECTS = "projects:" + url_base
        self.releasefilestore = releasefilestore

    def iscontained(self, projectname):
        return self.redis.hexists(self.PROJECTS, projectname)

    def getprojectnames(self):
        """ return list of all projects which have been served. """
        keyvals = self.redis.hgetall(self.PROJECTS)
        return set([key for key,val in keyvals.items() if val])

    def getreleaselinks(self, projectname, refresh=False):
        """ return all releaselinks from the index and referenced scrape
        pages.  If refresh is True, re-get all index and scrape pages.
        """
        if not refresh:
            res = self.redis.hget(self.PROJECTS, projectname)
            if res:
                relpaths = json.loads(res)
                return [self.releasefilestore.getentry(relpath)
                            for relpath in relpaths]
        # mark it as being accessed if it hasn't already
        self.redis.hsetnx(self.PROJECTS, projectname, "")

        url = self.url_simple + projectname + "/"
        log.debug("visiting index %s", url)
        response = self.htmlcache.get(url, refresh=refresh)
        if response.status_code != 200:
            return None
        assert response.text is not None, response.text
        result = parse_index(response.url, response.text)
        for crawlurl in result.crawllinks:
            log.debug("visiting crawlurl %s", crawlurl)
            response = self.htmlcache.get(crawlurl.url, refresh=refresh)
            log.debug("crawlurl %s %s", crawlurl, response.status_code)
            if response.status_code == 200:
                result.parse_index(DistURL(response.url), response.text)
        releaselinks = list(result.releaselinks)
        releaselinks.sort(reverse=True)
        entries = [self.releasefilestore.maplink(link, refresh=refresh)
                        for link in releaselinks]
        dumplist = [entry.relpath for entry in entries]
        self.redis.hset(self.PROJECTS, projectname, json.dumps(dumplist))
        return entries


class ReleaseFileStore:
    HASHDIRLEN = 2

    def __init__(self, redis, basedir):
        self.redis = redis
        self.basedir = basedir

    def maplink(self, link, refresh):
        entry = self.getentry_fromlink(link)
        if not entry or refresh:
            mapping = dict(url=link.url_nofrag, md5=link.md5)
            entry.set(mapping)
        return entry

    def canonical_relpath(self, link):
        m = md5(link.url_nofrag)
        return "%s/%s" %(m.hexdigest()[:self.HASHDIRLEN], link.basename)

    def getentry_fromlink(self, link):
        return self.getentry(self.canonical_relpath(link))

    def getentry(self, relpath):
        return RelPathEntry(self.redis, relpath, self.basedir)

    def iterfile(self, relpath, httpget, chunksize=8192):
        entry = self.getentry(relpath)
        target = entry.filepath
        if entry.headers is None:
            # we get and cache the file and some http headers from remote
            r = httpget(entry.url, allow_redirects=True)
            assert r.status_code == 200
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
        self._mapping = redis.hgetall(self.SITEPATH + relpath)

    @property
    def basename(self):
        return self.relpath.split("/")[1]

    def __nonzero__(self):
        return bool(self._mapping)

    def __eq__(self, other):
        return (self.relpath == other.relpath and
                self._mapping == other._mapping)

    url = propmapping("url")
    md5 = propmapping("md5")
    _headers = propmapping("_headers")
    #download = propmapping("download")

    @property
    def headers(self):
        if self._headers is not None:
            return json.loads(self._headers)

    def set(self, mapping):
        self.redis.hmset(self.SITEPATH + self.relpath, mapping)
        self._mapping.update(mapping)



class RefreshManager:
    def __init__(self, extdb, xom):
        self.extdb = extdb
        self.xom = xom
        self.redis = extdb.htmlcache.redis
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

def parse_http_date_to_posix(date):
    time = parse_date(date)
    ### DST?
    return (time - datetime.datetime(1970, 1, 1)).total_seconds()

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
        print link.relpath, link.md5
        #print "   ", link.url
    elapsed = py.std.time.time() - now
    print "retrieval took %.3f seconds" % elapsed
    return True

@hookimpl()
def resource_extdb(xom):
    htmlcache = xom.hook.resource_htmlcache(xom=xom)
    target = py.path.local(os.path.expanduser(xom.config.args.datadir))
    releasefilestore = ReleaseFileStore(htmlcache.redis, target)
    extdb = ExtDB(xom.config.args.url_base, htmlcache, releasefilestore)
    #extdb.scanner = pypichangescan(config.args.url_base+"pypi", htmlcache)
    return extdb


@hookimpl()
def resource_htmlcache(xom):
    redis = xom.hook.resource_redis(xom=xom)
    httpget = xom.hook.resource_httpget(xom=xom)
    return HTMLCache(redis, httpget)

class FatalResponse:
    status_code = -1

    def __init__(self, excinfo=None):
        self.excinfo = excinfo

@hookimpl()
def resource_httpget(xom):
    import requests.exceptions
    session = requests.session()
    def httpget(url, allow_redirects):
        try:
            return session.get(url, stream=True,
                               allow_redirects=allow_redirects)
        except requests.exceptions.RequestException:
            return FatalResponse(sys.exc_info())
    return httpget


#def mirroring_httpget_releasefile(httpget):
#    def mirror_httpget(url, allow_redirects=False):

