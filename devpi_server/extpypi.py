"""

Implementation of the database layer for PyPI Package serving and
testresult storage.

"""
import json
import re
import sys

from ._pip import HTMLPage

from .types import propmapping
from .urlutil import DistURL, joinpath

from logging import getLogger
assert __name__ == "devpi_server.extpypi"
log = getLogger(__name__)

class IndexParser:
    ALLOWED_ARCHIVE_EXTS = ".egg .tar.gz .tar.bz2 .tar .tgz .zip".split()

    def __init__(self, projectname):
        self.projectname = projectname.lower()
        self.basename2link = {}
        self.crawllinks = set()
        self.egglinks = []

    def _mergelink_ifbetter(self, newurl):
        entry = self.basename2link.get(newurl.basename)
        if entry is None or (not entry.md5 and newurl.md5):
            self.basename2link[newurl.basename] = newurl
            log.debug("adding link %s", newurl)
        else:
            log.debug("ignoring candidate link %s", newurl)

    @property
    def releaselinks(self):
        """ return sorted releaselinks list """
        l = list(self.basename2link.values())
        l.sort(reverse=True)
        return self.egglinks + l

    def parse_index(self, disturl, html, scrape=True):
        p = HTMLPage(html, disturl.url)
        seen = set()
        for link in p.links:
            newurl = DistURL(link.url)
            eggfragment = newurl.eggfragment
            if scrape and eggfragment:
                filename = eggfragment.replace("_", "-")
                if filename.lower().startswith(self.projectname + "-"):
                    # XXX seems we have to maintain a particular
                    # order to keep pip/easy_install happy with some
                    # packages (e.g. nose)
                    self.egglinks.insert(0, newurl)
                else:
                    log.debug("skip egg link %s (projectname: %s)",
                              newurl, self.projectname)
                continue
            nameversion, ext = newurl.splitext_archive()
            parts = re.split(r'-\d+', nameversion)
            projectname = parts[0]
            #log.debug("checking %s, projectname %r, nameversion %s", newurl, self.projectname, nameversion)
            if len(parts) > 1 and ext.lower() in self.ALLOWED_ARCHIVE_EXTS and \
               projectname.lower() == self.projectname:
                self._mergelink_ifbetter(newurl)
                seen.add(newurl.url)
                continue
        if scrape:
            for link in p.rel_links():
                if link.url not in seen:
                    self.crawllinks.add(DistURL(link.url))

def parse_index(disturl, html, scrape=True):
    if not isinstance(disturl, DistURL):
        disturl = DistURL(disturl)
    projectname = disturl.basename or disturl.parentbasename
    parser = IndexParser(projectname)
    parser.parse_index(disturl, html, scrape=scrape)
    return parser

class XMLProxy(object):
    def __init__(self, proxy):
        self._proxy = proxy

    def changelog_last_serial(self):
        return self._execute("changelog_last_serial")

    def changelog_since_serial(self, serial):
        return self._execute("changelog_since_serial", serial)

    def _execute(self, method, *args):
        try:
            return getattr(self._proxy, method)(*args)
        except KeyboardInterrupt:
            raise
        except Exception:
            exc = sys.exc_info()[1]
            log.warn("%s: error %s with remote %s", method, exc, self._proxy)
            return None

class ExtDB:
    def __init__(self, url_base, redis, httpget, releasefilestore):
        self.redis = redis
        self.httpget = httpget
        self.url_base = url_base
        self.url_simple = url_base + "simple/"
        self.url_xmlrpc = url_base + "pypi"
        self.PROJECTS = "projects:" + url_base
        self.releasefilestore = releasefilestore

    def iscontained(self, projectname):
        return self.redis.hexists(self.PROJECTS, projectname)

    def getprojectnames(self):
        """ return list of all projects which have been served. """
        keyvals = self.redis.hgetall(self.PROJECTS)
        l = [key for key,val in keyvals.items() if val]
        l.sort()
        return l

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
        response = self.httpget(url, allow_redirects=True)
        if response.status_code != 200:
            assert response.status_code
            return response.status_code
        assert response.text is not None, response.text
        result = parse_index(response.url, response.text)
        for crawlurl in result.crawllinks:
            log.debug("visiting crawlurl %s", crawlurl)
            response = self.httpget(crawlurl.url, allow_redirects=True)
            log.debug("crawlurl %s %s", crawlurl, response)
            assert hasattr(response, "status_code")
            if response.status_code == 200:
                result.parse_index(DistURL(response.url), response.text,
                                   scrape=False)
            else:
                log.warn("crawlurl %s returned %s", crawlurl.url,
                        response.status_code)
                # XXX we should mark project for retry after one hour or so

        releaselinks = list(result.releaselinks)
        entries = [self.releasefilestore.maplink(link, refresh=refresh)
                        for link in releaselinks]
        dumplist = [entry.relpath for entry in entries]
        self.redis.hset(self.PROJECTS, projectname, json.dumps(dumplist))
        return entries


class RefreshManager:
    def __init__(self, extdb, xom):
        self.extdb = extdb
        self.xom = xom
        self.redis = extdb.redis
        self.PYPISERIAL = "pypiserial:" + extdb.url_base
        self.INVALIDSET = "invalid:" + extdb.url_base

    def spawned_pypichanges(self, proxy, proxysleep):
        log.debug("spawned_pypichanges starting")
        redis = self.redis
        current_serial = redis.get(self.PYPISERIAL)
        while 1:
            if current_serial is None:
                current_serial = proxy.changelog_last_serial()
                if current_serial is None:
                    proxysleep()
                    continue
                redis.set(self.PYPISERIAL, current_serial)
            else:
                current_serial = int(current_serial)
            log.debug("checking remote changelog [%s]...", current_serial)
            changelog = proxy.changelog_since_serial(current_serial)
            if changelog:
                log.debug("got changelog of size %d" %(len(changelog),))
                self.mark_refresh(changelog)
                current_serial += len(changelog)
                redis.set(self.PYPISERIAL, current_serial)
            proxysleep()

    def mark_refresh(self, changelog):
        projectnames = set([x[0] for x in changelog])
        redis = self.redis
        notcontained = set()
        changed = set()
        for name in projectnames:
            if self.extdb.iscontained(name):
                log.debug("marking invalid %r", name)
                changed.add(name)
                redis.sadd(self.INVALIDSET, name)
            else:
                notcontained.add(name)
        if notcontained:
            log.info("ignoring changed projects: %r", notcontained)
        if changed:
            log.info("invalidated projects: %r", changed)

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
            log.info("picking up invalidated projects %r", names)
            for name in names:
                self.extdb.getreleaselinks(name, refresh=True)
                self.redis.srem(self.INVALIDSET, name)
