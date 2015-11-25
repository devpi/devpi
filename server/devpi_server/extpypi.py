"""

Implementation of the database layer for PyPI Package serving and
toxresult storage.

"""

from __future__ import unicode_literals

import time
import os.path

from devpi_common.vendor._pip import HTMLPage

from devpi_common.url import URL
from devpi_common.metadata import BasenameMeta
from devpi_common.metadata import is_archive_of_project
from devpi_common.validation import normalize_name

from .model import BaseStage, make_key_and_href, SimplelinkMeta
from .keyfs import load_from_file, dump_to_file
from .readonly import ensure_deeply_readonly
from .log import threadlog


class IndexParser:

    def __init__(self, project):
        self.project = normalize_name(project)
        self.basename2link = {}
        self.crawllinks = set()
        self.egglinks = []

    def _mergelink_ifbetter(self, newurl):
        entry = self.basename2link.get(newurl.basename)
        if entry is None or (not entry.hash_spec and newurl.hash_spec):
            self.basename2link[newurl.basename] = newurl
            threadlog.debug("indexparser: adding link %s", newurl)
        else:
            threadlog.debug("indexparser: ignoring candidate link %s", newurl)

    @property
    def releaselinks(self):
        """ return sorted releaselinks list """
        l = sorted(map(BasenameMeta, self.basename2link.values()),
                   reverse=True)
        return self.egglinks + [x.obj for x in l]

    def parse_index(self, disturl, html, scrape=True):
        p = HTMLPage(html, disturl.url)
        seen = set()
        for link in p.links:
            newurl = URL(link.url)
            if not newurl.is_valid_http_url():
                continue
            eggfragment = newurl.eggfragment
            if scrape and eggfragment:
                if not normalize_name(eggfragment).startswith(self.project):
                    threadlog.debug("skip egg link %s (project: %s)",
                              newurl, self.project)
                    continue
                if newurl.basename:
                    # XXX seems we have to maintain a particular
                    # order to keep pip/easy_install happy with some
                    # packages (e.g. nose)
                    if newurl not in self.egglinks:
                        self.egglinks.insert(0, newurl)
                else:
                    threadlog.warn("cannot handle egg directory link (svn?) "
                                   "skipping: %s (project: %s)",
                                   newurl, self.project)
                continue
            if is_archive_of_project(newurl, self.project):
                if not newurl.is_valid_http_url():
                    threadlog.warn("unparseable/unsupported url: %r", newurl)
                else:
                    seen.add(newurl.url)
                    self._mergelink_ifbetter(newurl)
                    continue
        if scrape:
            for link in p.rel_links():
                if link.url not in seen:
                    disturl = URL(link.url)
                    if disturl.is_valid_http_url():
                        self.crawllinks.add(disturl)

def parse_index(disturl, html, scrape=True):
    if not isinstance(disturl, URL):
        disturl = URL(disturl)
    project = disturl.basename or disturl.parentbasename
    parser = IndexParser(project)
    parser.parse_index(disturl, html, scrape=scrape)
    return parser


def perform_crawling(pypistage, result, numthreads=10):
    pending = set(result.crawllinks)
    while pending:
        try:
            crawlurl = pending.pop()
        except KeyError:
            break
        threadlog.info("visiting crawlurl %s", crawlurl)
        response = pypistage.httpget(crawlurl.url, allow_redirects=True)
        threadlog.info("crawlurl %s %s", crawlurl, response)
        assert hasattr(response, "status_code")
        if not isinstance(response, int) and response.status_code == 200:
            ct = response.headers.get("content-type", "").lower()
            if ct.startswith("text/html"):
                result.parse_index(
                    URL(response.url), response.text, scrape=False)
                continue
        threadlog.warn("crawlurl %s status %s", crawlurl, response)

PYPIURL_SIMPLE = "https://pypi.python.org/simple/"

class PyPIStage(BaseStage):
    def __init__(self, xom, username, index, ixconfig):
        super(PyPIStage, self).__init__(xom, username, index, ixconfig)
        self.httpget = self.xom.httpget  # XXX is requests/httpget multi-thread safe?
        self.cache_expiry = xom.config.args.pypi_cache_expiry
        self.xom = xom
        if xom.is_replica():
            url = xom.config.master_url
            self.PYPIURL_SIMPLE = url.joinpath("root/pypi/+simple/").url
        else:
            self.PYPIURL_SIMPLE = PYPIURL_SIMPLE

    @property
    def cache_projectnames(self):
        """ filesystem-persistent cache for full list of projectnames. """
        # we could keep this info inside keyfs but pypi.python.org
        # produces a 3MB list of names and it changes often which
        # would spam the database.
        try:
            return self.xom.get_singleton(self.name, "projectnames")
        except KeyError:
            cache_projectnames = ProjectNamesCache(
                expiry_time=self.cache_expiry,
                filepath=self.keyfs.basedir.join(self.name, ".projects"))
            self.xom.set_singleton(self.name, "projectnames", cache_projectnames)
            return cache_projectnames

    @property
    def cache_link_updates(self):
        """ per-xom RAM cache for keeping track when we last updated simplelinks. """
        # we could keep this info in keyfs but it would lead to a write
        # for each remote check.
        try:
            return self.xom.get_singleton(self.name, "project_retrieve_times")
        except KeyError:
            c = ProjectUpdateCache(expiry_time=self.cache_expiry)
            self.xom.set_singleton(self.name, "project_retrieve_times", c)
            return c

    def _get_remote_projects(self):
        headers = {"Accept": "text/html"}
        response = self.httpget(self.PYPIURL_SIMPLE, extra_headers=headers)
        if response.status_code != 200:
            raise self.UpstreamError("URL %r returned %s",
                                self.PYPIURL_SIMPLE, response.status_code)
        page = HTMLPage(response.text, response.url)
        projects = set()
        baseurl = URL(response.url)
        basehost = baseurl.replace(path='')
        for link in page.links:
            newurl = URL(link.url)
            if not newurl.is_valid_http_url():
                continue
            if not newurl.path.startswith(baseurl.path):
                continue
            if basehost != newurl.replace(path=''):
                continue
            projects.add(newurl.basename)
        return projects

    def list_projects_perstage(self):
        """ return set of all projects served through the mirror. """
        if self.cache_projectnames.is_fresh():
            projects = self.cache_projectnames.get()
        else:
            # no fresh projects or None at all, let's go remote
            try:
                projects = self._get_remote_projects()
            except self.UpstreamError:
                if not self.cache_projectnames.exists():
                    raise
                threadlog.warn("using stale projects list")
                projects = self.cache_projectnames.get()
            else:
                old = self.cache_projectnames.get()
                if not self.cache_projectnames.exists() or old != projects:
                    self.cache_projectnames.set(projects)

                    # trigger an initial-load event
                    k = self.keyfs.MIRRORNAMESINIT(user=self.username, index=self.index)
                    if k.get() == 0:
                        self.keyfs.restart_as_write_transaction()
                        k.set(1)

        return projects

    def _save_cache_links(self, project, links, serial):
        assert isinstance(serial, int)
        assert project == normalize_name(project), project
        data = {"serial": serial, "links": links}
        key = self.key_projsimplelinks(project)
        old = key.get()
        if old != data:
            threadlog.debug("saving changed simplelinks for %s: %s", project, data)
            key.set(data)
        # XXX if the transaction fails the links are still marked
        # as refreshed but the data was not persisted.  It's a rare
        # enough event (tm) to not worry too much, though.
        # (we can, however, easily add a
        # keyfs.tx.on_commit_success(callback) method.
        self.cache_link_updates.refresh(project)

    def _load_cache_links(self, project):
        cache = self.key_projsimplelinks(project).get()
        if cache:
            return (self.cache_link_updates.is_fresh(project),
                    cache["links"], cache["serial"])
        return False, None, -1

    def clear_simplelinks_cache(self, project):
        # we have to set to an empty dict instead of removing the key, so
        # replicas behave correctly
        self.key_projsimplelinks(project).set({})
        threadlog.debug("cleared cache for %s", project)

    def get_simplelinks_perstage(self, project):
        """ return all releaselinks from the index and referenced scrape
        pages, returning cached entries if we have a recent enough
        request stored locally.

        Raise UpstreamError if the pypi server cannot be reached or
        does not return a fresh enough page although we know it must
        exist.
        """
        project = normalize_name(project)
        is_fresh, links, cache_serial = self._load_cache_links(project)
        if is_fresh:
            return links

        # get the simple page for the project
        url = self.PYPIURL_SIMPLE + project + "/"
        threadlog.debug("reading index %s", url)
        response = self.httpget(url, allow_redirects=True)
        if response.status_code != 200:
            # if we have and old result, return it. While this will
            # miss the rare event of actual project deletions it allows
            # to stay resilient against server misconfigurations.
            if links is not None and links != ():
                threadlog.error("serving stale links for %r, url %r responded %r",
                                project, url, response.status_code)
                return links
            if response.status_code == 404:
                # we get a 404 if a project does not exist. We persist
                # this result so replicas see it as well.  After the
                # dump cache expires new requests will retry and thus
                # detect new projects and their releases.
                # Note that we use an empty tuple (instead of the usual
                # list) so has_project_per_stage() can determine it as a
                # non-existing project.
                self.keyfs.restart_as_write_transaction()
                self._save_cache_links(project, (), -1)
                return ()

            # we don't have an old result and got a non-404 code.
            raise self.UpstreamError("%s status on GET %s" %
                                     (response.status_code, url))

        # pypi.python.org provides X-PYPI-LAST-SERIAL header in case of 200 returns.
        # devpi-master may provide a 200 but not supply the header
        # (it's really a 404 in disguise and we should change
        # devpi-server behaviour since pypi.python.org serves 404
        # on non-existing projects for a longer time now).
        # Returning a 200 with "no such project" was originally meant to
        # provide earlier versions of easy_install/pip to request the full
        # simple page.
        serial = int(response.headers.get(str("X-PYPI-LAST-SERIAL"), "-1"))

        if serial < cache_serial:
            threadlog.warn("serving cached links for %s "
                           "because returned serial %s, cache_serial %s is better!",
                           response.url, serial, cache_serial)
            return links

        threadlog.debug("%s: got response with serial %s", project, serial)

        # check returned url has the same normalized name
        ret_project = response.url.strip("/").split("/")[-1]
        assert project == normalize_name(ret_project)


        # parse simple index's link and perform crawling
        assert response.text is not None, response.text
        result = parse_index(response.url, response.text)
        perform_crawling(self, result)
        releaselinks = list(result.releaselinks)

        # first we try to process mirror links without an explicit write transaction.
        # if all links already exist in storage we might then return our already
        # cached information about them.  Note that _save_cache_links() will
        # implicitely update non-persisted cache timestamps.
        def map_and_dump():
            # both maplink() and _save_cache_links() will not modify
            # storage if there are no changes so they operate fine within a
            # read-transaction if nothing changed.
            entries = [self.filestore.maplink(link) for link in releaselinks]
            links = [make_key_and_href(entry) for entry in entries]
            self._save_cache_links(project, links, serial)

            # make project appear in projects list even
            # before we next check up the full list with remote
            threadlog.info("setting projects cache for %r", project)
            self.cache_projectnames.get_inplace().add(project)
            return links

        try:
            return map_and_dump()
        except self.keyfs.ReadOnly:
            pass

        # we know that some links changed in this simple page.
        # On the master we need to write-update, on the replica
        # we wait for the changes to arrive (changes were triggered
        # by our http request above) because have no direct write
        # access to the db other than through the replication thread.
        if self.xom.is_replica():
            # we have already triggered the master above
            # and now need to wait until the parsed new links are
            # transferred back to the replica
            devpi_serial = int(response.headers["X-DEVPI-SERIAL"])
            threadlog.debug("get_simplelinks pypi: waiting for devpi_serial %r",
                            devpi_serial)
            self.keyfs.notifier.wait_tx_serial(devpi_serial)
            threadlog.debug("get_simplelinks pypi: finished waiting for devpi_serial %r",
                            devpi_serial)
            # XXX raise TransactionRestart to get a consistent clean view
            self.keyfs.commit_transaction_in_thread()
            self.keyfs.begin_transaction_in_thread()
            is_fresh, links, cache_serial = self._load_cache_links(project)
            if links is not None:
                self.cache_link_updates.refresh(project)
                return links
            raise self.UpstreamError("no cache links from master for %s" %
                                     project)
        else:
            # we are on the master and something changed and we are
            # in a readonly-transaction so we need to start a write
            # transaction and perform map_and_dump.
            self.keyfs.restart_as_write_transaction()
            return map_and_dump()

    def has_project_perstage(self, project):
        links = self.get_simplelinks_perstage(project)
        if links == ():  # marker for non-existing project, see get_simplelinks_perstage
            return False
        return True

    def list_versions_perstage(self, project):
        return set(x.get_eggfragment_or_version()
                   for x in map(SimplelinkMeta, self.get_simplelinks_perstage(project)))

    def get_versiondata_perstage(self, project, version, readonly=True):
        project = normalize_name(project)
        verdata = {}
        for sm in map(SimplelinkMeta, self.get_simplelinks_perstage(project)):
            link_version = sm.get_eggfragment_or_version()
            if version == link_version:
                if not verdata:
                    verdata['name'] = project
                    verdata['version'] = version
                elinks = verdata.setdefault("+elinks", [])
                entrypath = sm._url.path
                elinks.append({"rel": "releasefile", "entrypath": entrypath})
        if readonly:
            return ensure_deeply_readonly(verdata)
        return verdata


def itervalues(d):
    return getattr(d, "itervalues", d.values)()
def iteritems(d):
    return getattr(d, "iteritems", d.items)()


class ProjectNamesCache:
    """ Helper class for maintaining project names from a mirror. """
    def __init__(self, expiry_time, filepath):
        self._timestamp = -1
        self._expiry_time = expiry_time
        self.filepath = str(filepath)
        self._data = set()

    def exists(self):
        if self._timestamp != -1:
            return True
        if self.filepath is not None and os.path.exists(self.filepath):
            self._timestamp, self._data = load_from_file(self.filepath)
            return True
        return False

    def is_fresh(self):
        return self.exists() and (time.time() - self._timestamp) < self._expiry_time

    def get(self):
        """ Get a copy of the cached data. """
        return set(self._data)

    def get_inplace(self):
        """ Get cached data in-place. """
        return self._data

    def set(self, data):
        """ Set data, updating timestamp and writing to local file"""
        if data is not self._data:
            self._data = data.copy()
        self._timestamp = time.time()
        if self.filepath is not None:
            dump_to_file((self._timestamp, self._data), self.filepath)


class ProjectUpdateCache:
    """ Helper class to manage when we last updated something project specific. """
    def __init__(self, expiry_time):
        self.expiry_time = expiry_time
        self._project2time = {}

    def is_fresh(self, project):
        t = self._project2time.get(project)
        if t is not None:
            if (time.time() - t) < self.expiry_time:
                return True
        return False

    def get_timestamp(self, project):
        return self._project2time.get(project, 0)

    def refresh(self, project):
        self._project2time[project] = time.time()

    def expire(self, project):
        self._project2time.pop(project, None)
