"""

Implementation of the database layer for PyPI Package serving and
testresult storage.

"""
import py
import sys
import threading
html = py.xml.html

from devpi_common.vendor._pip import HTMLPage

from devpi_common.s_url import DistURL
from devpi_common.validation import normalize_name

from .db import ProjectInfo

from logging import getLogger
assert __name__ == "devpi_server.extpypi"
log = getLogger(__name__)

CONCUCCRENT_CRAWL = False


class IndexParser:

    def __init__(self, projectname):
        self.projectname = normalize_name(projectname)
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
            if not newurl.is_valid_http_url():
                continue
            eggfragment = newurl.eggfragment
            if scrape and eggfragment:
                if normalize_name(eggfragment).startswith(self.projectname):
                    # XXX seems we have to maintain a particular
                    # order to keep pip/easy_install happy with some
                    # packages (e.g. nose)
                    if newurl not in self.egglinks:
                        self.egglinks.insert(0, newurl)
                else:
                    log.debug("skip egg link %s (projectname: %s)",
                              newurl, self.projectname)
                continue
            if newurl.is_archive_of_project(self.projectname):
                seen.add(newurl.url)
                self._mergelink_ifbetter(newurl)
                continue
        if scrape:
            for link in p.rel_links():
                if link.url not in seen:
                    disturl = DistURL(link.url)
                    if disturl.is_valid_http_url():
                        self.crawllinks.add(disturl)

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

def perform_crawling(extdb, result, numthreads=10):
    pending = set(result.crawllinks)
    def process():
        while 1:
            try:
                crawlurl = pending.pop()
            except KeyError:
                break
            log.info("visiting crawlurl %s", crawlurl)
            response = extdb.httpget(crawlurl.url, allow_redirects=True)
            log.info("crawlurl %s %s", crawlurl, response)
            assert hasattr(response, "status_code")
            if not isinstance(response, int) and response.status_code == 200:
                ct = response.headers.get("content-type", "").lower()
                if ct.startswith("text/html"):
                    result.parse_index(
                        DistURL(response.url), response.text, scrape=False)
                    continue
            log.warn("crawlurl %s status %s", crawlurl, response)

    if not CONCUCCRENT_CRAWL:
        while pending:
            process()
    else:
        threads = []
        numpending = len(pending)
        for i in range(min(numthreads, numpending)):
            t = threading.Thread(target=process)
            t.setDaemon(True)
            threads.append(t)
            t.start()

        log.debug("joining threads")
        for t in threads:
            t.join()


def invalidate_on_version_change(basedir):
    verfile = basedir.join(".mirrorversion")
    if not verfile.check():
        ver = "0"
    else:
        ver = verfile.read()
    if ver != ExtDB.VERSION:
        if basedir.check():
            log.info("version format change: removing root/pypi state")
            basedir.remove()
    verfile.dirpath().ensure(dir=1)
    verfile.write(ExtDB.VERSION)

class ExtDB:
    VERSION = "1"
    name = "root/pypi"
    ixconfig = dict(bases=(), volatile=False, type="mirror")

    def __init__(self, keyfs, httpget, filestore, proxy):
        self.keyfs = keyfs
        self.httpget = httpget
        self.filestore = filestore
        invalidate_on_version_change(keyfs.basedir.join("root", "pypi"))
        self.init_pypi_mirror(proxy)

    def getcontained(self):
        return self.keyfs.PYPILINKS.listnames("name")

    def getprojectnames(self):
        """ return list of all projects which have been served. """
        return sorted(self.name2serials)

    getprojectnames_perstage = getprojectnames

    def _dump_project_cache(self, projectname, dumplist, serial):
        normname = normalize_name(projectname)
        data = {"serial": serial,
                "entrylist": dumplist,
                "projectname": projectname}
        self.keyfs.PYPILINKS(name=normname).set(data)

    def _load_project_cache(self, projectname):
        normname = normalize_name(projectname)
        return self.keyfs.PYPILINKS(name=normname).get(None)

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
        cache = self._load_project_cache(projectname)
        if cache is not None and cache["serial"] >= refresh:
            return [self.filestore.getentry(relpath)
                        for relpath in cache["entrylist"]]

        info = self.get_project_info(projectname)
        if not info:
            return 404
        url = PYPIURL_SIMPLE + info.name + "/"
        log.debug("visiting index %s", url)
        response = self.httpget(url, allow_redirects=True)
        if response.status_code != 200:
            return response.status_code
        real_projectname = response.url.strip("/").split("/")[-1]
        assert real_projectname == info.name
        serial = int(response.headers["X-PYPI-LAST-SERIAL"])
        if not isinstance(refresh, bool) and isinstance(refresh, int):
            if serial < refresh:
                log.warn("%s: pypi returned serial %s, expected %s",
                         real_projectname, serial, refresh)
                return -2  # the page we got is not fresh enough
        log.debug("%s: got response with serial %s" %
                  (real_projectname, serial))
        assert response.text is not None, response.text
        result = parse_index(response.url, response.text)
        perform_crawling(self, result)
        releaselinks = list(result.releaselinks)
        entries = [self.filestore.maplink(link, refresh=refresh)
                        for link in releaselinks]
        dumplist = [entry.relpath for entry in entries]
        self._dump_project_cache(real_projectname, dumplist, serial)
        return entries

    getreleaselinks_perstage = getreleaselinks

    def get_project_info(self, name):
        norm_name = normalize_name(name)
        name = self.normname2name.get(norm_name, norm_name)
        if name in self.name2serials:
            return ProjectInfo(self, name)

    get_project_info_perstage = get_project_info

    def op_with_bases(self, opname, **kw):
        return [(self, getattr(self, opname)(**kw))]

    def get_projectconfig(self, name):
        releaselinks = self.getreleaselinks(name)
        if isinstance(releaselinks, int):
            return releaselinks
        data = {}
        for link in releaselinks:
            url = DistURL(link.url)
            if link.eggfragment:
                version = "egg=" + link.eggfragment
            else:
                _, version = url.pkgname_and_version
            verdata = data.setdefault(version, {})
            files = verdata.setdefault("+files", {})
            files[url.basename] = link.relpath
        return data

    get_projectconfig_perstage = get_projectconfig

    def get_description(self, name, version):
        link = "https://pypi.python.org/pypi/%s/%s/" % (name, version)
        return html.div("please refer to description on remote server ",
            html.a(link, href=link)).unicode(indent=2)

    def init_pypi_mirror(self, proxy):
        """ initialize pypi mirror if no mirror state exists. """
        self.proxy = proxy
        name2serials = self.keyfs.PYPISERIALS.get({})
        if not name2serials:
            log.info("retrieving initial name/serial list")
            name2serials = proxy.list_packages_with_serial()
            if name2serials is None:
                from devpi_server.main import fatal
                fatal("mirror initialization failed: "
                      "pypi.python.org not reachable")
            self.keyfs.PYPISERIALS.set(name2serials)
        else:
            log.info("reusing already cached name/serial list")
        self.name2serials = name2serials
        # create a mapping of normalized name to real name
        self.normname2name = d = dict()
        for name in name2serials:
            norm = normalize_name(name)
            if norm != name:
                d[norm] = name

    def _set_project_serial(self, name, serial):
        """ set the current serial and fill normalization table
        if project does not exist.
        """
        try:
            current_serial = self.name2serials[name]
        except KeyError:
            self.name2serials[name] = serial
            n = normalize_name(name)
            if n != name:
                self.normname2name[n] = name
        else:
            self.name2serials[name] = serial

    def spawned_pypichanges(self, proxy, proxysleep):
        log.info("changelog/update tasks starting")
        keyfs = self.keyfs
        while 1:
            # get changes since the maximum serial we are aware of
            current_serial = max(itervalues(self.name2serials))
            log.debug("querying pypi changelog since %s", current_serial)
            changelog = proxy.changelog_since_serial(current_serial)
            self.process_changelog(changelog)
            self.process_refreshes()
            proxysleep()

    def process_changelog(self, changelog):
        if not changelog:
            return
        names = set()
        for x in changelog:
            name, version, action, date, serial = x
            # XXX remove names if action == "remove"
            # and version is None
            self.name2serials[name] = max(self.name2serials.get(name, 0),
                                     serial)
            names.add(name)
        log.debug("processed changelog of size %d: %s" %(
                  len(changelog), names))
        self.keyfs.PYPISERIALS.set(self.name2serials)

    def process_refreshes(self):
        # walk through all mirrored projects and trigger updates if needed
        for name in self.getcontained():
            serial = self.name2serials.get(name, 0)
            self.getreleaselinks(name, refresh=serial)

PYPIURL_SIMPLE = "https://pypi.python.org/simple/"
PYPIURL = "https://pypi.python.org/"

def itervalues(d):
    return getattr(d, "itervalues", d.values)()
def iteritems(d):
    return getattr(d, "iteritems", d.items)()
