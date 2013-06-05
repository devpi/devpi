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

    def list_packages_with_serial(self):
        return self._execute("list_packages_with_serial")

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
        self.xom = xom

    def getcontained(self):
        return self.keyfs.PYPILINKS.listnames("name")

    def getprojectnames(self):
        """ return list of all projects which have been served. """
        # XXX return full upstream list?
        return sorted(self.keyfs.PYPILINKS.listnames("name"))

    def _dump_projectlinks(self, projectname, dumplist, serial):
        newlist = [serial] + dumplist
        self.keyfs.PYPILINKS(name=projectname).set(newlist)

    def _load_projectlinks(self, projectname):
        res = self.keyfs.PYPILINKS(name=projectname).get(None)
        if res:
            serial = res.pop(0)
            assert isinstance(serial, int)
            return serial, res
        return None, None

    def getreleaselinks(self, projectname, refresh=0):
        """ return all releaselinks from the index and referenced scrape
        pages.   If we have cached entries return them if they relate to
        at least the specified "refresh" serial number.  Otherwise
        ask pypi.python.org for the simple page and process it if
        it relates to at least the specified refresh serial.

        If the pypi server cannot be reached return -1
        If the cache is stale and could not be refreshed return -2.
        """
        assert not isinstance(refresh, bool), repr(refresh)
        serial, res = self._load_projectlinks(projectname)
        if res is not None and serial >= refresh:
            return [self.releasefilestore.getentry(relpath) for relpath in res]

        url = PYPIURL_SIMPLE + projectname + "/"
        log.debug("visiting index %s", url)
        response = self.httpget(url, allow_redirects=True)
        if response.status_code != 200:
            return response.status_code
        serial = int(response.headers["X-PYPI-LAST-SERIAL"])
        if not isinstance(refresh, bool) and isinstance(refresh, int):
            if serial < refresh:
                log.warn("%s: pypi returned serial %s, expected %s",
                         projectname, serial, refresh)
                return -2  # the page we got is not fresh enough
        log.debug("%s: got response with serial %s" % (projectname, serial))
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
        self._dump_projectlinks(projectname, dumplist, serial)
        return entries

    def spawned_pypichanges(self, proxy, proxysleep):
        log.info("changelog/update tasks starting")
        keyfs = self.keyfs
        name2serials = keyfs.PYPISERIALS.get({})
        while 1:
            if not name2serials:
                log.debug("retrieving initial name/serial list")
                init_name2serials = proxy.list_packages_with_serial()
                if init_name2serials is None:
                    proxysleep()
                    continue
                for name, serial in iteritems(init_name2serials):
                    name2serials[name.lower()] = serial
                keyfs.PYPISERIALS.set(name2serials)
            else:
                # get changes since the maximum serial we are aware of
                current_serial = max(itervalues(name2serials))
                log.debug("querying pypi changelog since %s", current_serial)
                changelog = proxy.changelog_since_serial(current_serial)
                if changelog:
                    names = set()
                    for x in changelog:
                        name, version, action, date, serial = x
                        # XXX remove names if action == "remove"
                        # and version is None
                        name = name.lower()
                        name2serials[name] = max(name2serials.get(name, 0),
                                                 serial)
                        names.add(name)
                    log.debug("got changelog of size %d: %s" %(
                              len(changelog), names))
                    keyfs.PYPISERIALS.set(name2serials)

            # walk through all mirrored projects and trigger updates if needed
            for name in self.getcontained():
                name = name.lower()
                serial = name2serials[name]
                self.getreleaselinks(name, refresh=serial)

            proxysleep()

PYPIURL_SIMPLE = "https://pypi.python.org/simple/"
PYPIURL = "https://pypi.python.org/"

def itervalues(d):
    return getattr(d, "itervalues", d.values)()
def iteritems(d):
    return getattr(d, "iteritems", d.items)()
