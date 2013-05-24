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
    name = "ext/pypi"

    def __init__(self, xom):
        self.keyfs = xom.keyfs
        self.httpget = xom.httpget
        self.releasefilestore = xom.releasefilestore
        self._inprogress = set()

    def iscontained(self, projectname):
        return (self.keyfs.HPYPIPROJECTS(name=projectname).exists() or
                projectname in self._inprogress)

    def getprojectnames(self):
        """ return list of all projects which have been served. """
        l = list(self.keyfs.HPYPIPROJECTS.listnames("name"))
        l.sort()
        return l

    def _dump_projectlinks(self, projectname, dumplist):
        self.keyfs.HPYPIPROJECTS(name=projectname).set(dumplist)

    def _load_projectlinks(self, projectname):
        res = self.keyfs.HPYPIPROJECTS(name=projectname).get(None)
        if res:
            return res
        return None

    def getreleaselinks(self, projectname, refresh=False):
        """ return all releaselinks from the index and referenced scrape
        pages.  If refresh is True, re-get all index and scrape pages.
        """
        if not refresh:
            res = self._load_projectlinks(projectname)
            if res is not None:
                return [self.releasefilestore.getentry(relpath)
                            for relpath in res]

        # the async changelog-checking might run any time and we need to
        # make sure it consider this project before we read pypi.
        # We therefore mark it as being accessed
        self._inprogress.add(projectname)

        url = PYPIURL_SIMPLE + projectname + "/"
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
        self._dump_projectlinks(projectname, dumplist)
        self._inprogress.remove(projectname)
        return entries

PYPIURL_SIMPLE = "https://pypi.python.org/simple/"
PYPIURL = "https://pypi.python.org/"

class RefreshManager:
    def __init__(self, extdb, xom):
        self.extdb = extdb
        self.xom = xom
        self.keyfs = xom.keyfs

    def spawned_pypichanges(self, proxy, proxysleep):
        log.debug("spawned_pypichanges starting")
        keyfs = self.keyfs
        current_serial = keyfs.PYPISERIAL.get(None)
        while 1:
            if current_serial is None:
                current_serial = proxy.changelog_last_serial()
                if current_serial is None:
                    proxysleep()
                    continue
                keyfs.PYPISERIAL.set(current_serial)
            log.debug("checking remote changelog [%s]...", current_serial)
            changelog = proxy.changelog_since_serial(current_serial)
            if changelog:
                log.debug("got changelog of size %d" %(len(changelog),))
                self.mark_refresh(changelog)
                current_serial += len(changelog)
                keyfs.PYPISERIAL.set(current_serial)
            proxysleep()

    def mark_refresh(self, changelog):
        projectnames = set([x[0] for x in changelog])
        keyfs = self.keyfs
        notcontained = set()
        changed = set()
        for name in projectnames:
            if self.extdb.iscontained(name):
                log.debug("marking invalid %r", name)
                changed.add(name)
            else:
                notcontained.add(name)
        if notcontained:
            log.info("ignoring changed projects: %r", notcontained)
        if changed:
            with keyfs.PYPIINVALID.locked_update() as invalid:
                invalid.update(changed)
            log.info("invalidated projects: %r", changed)

    def spawned_refreshprojects(self, invalidationsleep):
        """ Invalidation task for re-freshing project indexes. """
        # note that this is written such that it could
        # be killed and restarted anytime without loosing
        # refreshing tasks (but possibly performing them twice)
        keyfs = self.keyfs
        while 1:
            names = keyfs.PYPIINVALID.get()
            if not names:
                invalidationsleep()
                continue
            log.info("refreshing invalidated projects %r", names)
            with keyfs.PYPIINVALID.locked_update() as invalidset:
                for name in names:
                    x = self.extdb.getreleaselinks(name, refresh=True)
                    if not isinstance(x, int):
                        invalidset.remove(name)
