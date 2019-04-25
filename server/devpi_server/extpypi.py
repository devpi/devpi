"""

Implementation of the database layer for PyPI Package serving and
toxresult storage.

"""

from __future__ import unicode_literals

import time

import re
from devpi_common.vendor._pip import HTMLPage

from devpi_common.url import URL
from devpi_common.metadata import BasenameMeta
from devpi_common.metadata import is_archive_of_project
from devpi_common.validation import normalize_name
from functools import partial
from .model import BaseStage, make_key_and_href, SimplelinkMeta
from .model import join_requires
from .model import InvalidIndexconfig, get_indexconfig
from .readonly import ensure_deeply_readonly
from .log import threadlog


class Link(URL):
    def __init__(self, url="", *args, **kwargs):
        self.requires_python = kwargs.pop('requires_python', None)
        URL.__init__(self, url, *args, **kwargs)


class IndexParser:

    def __init__(self, project):
        self.project = normalize_name(project)
        self.basename2link = {}
        self.crawllinks = set()
        self.egglinks = []

    def _mergelink_ifbetter(self, newlink):
        """
        Stores a link given it's better fit than an existing one (if any).

        A link with hash_spec replaces one w/o it, even if the latter got other
        non-empty attributes (like requires_python), unlike the former.
        As soon as the first link with hash_spec is encountered, those that
        appear later are ignored.
        """
        entry = self.basename2link.get(newlink.basename)
        if entry is None or not entry.hash_spec and (newlink.hash_spec or (
            not entry.requires_python and newlink.requires_python
        )):
            self.basename2link[newlink.basename] = newlink
            threadlog.debug("indexparser: adding link %s", newlink)
        else:
            threadlog.debug("indexparser: ignoring candidate link %s", newlink)

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
            newurl = Link(link.url, requires_python=link.requires_python)
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


class PyPIStage(BaseStage):
    def __init__(self, xom, username, index, ixconfig):
        super(PyPIStage, self).__init__(xom, username, index, ixconfig)
        self.httpget = self.xom.httpget  # XXX is requests/httpget multi-thread safe?
        self.cache_expiry = self.ixconfig.get(
            'mirror_cache_expiry', xom.config.args.mirror_cache_expiry)
        self.xom = xom
        self.offline = self.xom.config.args.offline_mode
        self.timeout = xom.config.args.request_timeout
        # list of locally mirrored projects
        self.key_projects = self.keyfs.PROJNAMES(user=username, index=index)
        if xom.is_replica():
            url = xom.config.master_url
            self.mirror_url = url.joinpath("%s/+simple/" % self.name).url
        else:
            url = URL(self.ixconfig['mirror_url'])
            self.mirror_url = url.asdir().url

    def delete(self):
        # delete all projects on this index
        for name in self.key_projects.get():
            self.del_project(name)
        self.key_projects.delete()
        BaseStage.delete(self)

    def modify(self, index=None, **kw):
        if 'type' in kw and self.ixconfig["type"] != kw['type']:
            raise InvalidIndexconfig(
                ["the 'type' of an index can't be changed"])
        kw.pop("type", None)
        ixconfig = get_indexconfig(
            self.xom.config.hook, type=self.ixconfig["type"], **kw)
        # modify user/indexconfig
        with self.user.key.update() as userconfig:
            newconfig = userconfig["indexes"][self.index]
            newconfig.update(ixconfig)
            threadlog.info("modified index %s: %s", self.name, ixconfig)
            self.ixconfig = newconfig
            return newconfig

    def add_project_name(self, project):
        project = normalize_name(project)
        projects = self.key_projects.get(readonly=False)
        if project not in projects:
            projects.add(project)
            self.key_projects.set(projects)

    def del_project(self, project):
        if not self.is_project_cached(project):
            raise KeyError("project not found")
        (is_expired, links, cache_serial) = self._load_cache_links(project)
        if links is not None:
            entries = (self._entry_from_href(x[1]) for x in links)
            entries = (x for x in entries if x.file_exists())
            for entry in entries:
                entry.delete()
        self.key_projsimplelinks(project).delete()
        projects = self.key_projects.get(readonly=False)
        if project in projects:
            projects.remove(project)
            self.cache_retrieve_times.expire(project)
            self.key_projects.set(projects)

    def del_versiondata(self, project, version, cleanup=True):
        project = normalize_name(project)
        if not self.has_project_perstage(project):
            raise self.NotFound("project %r not found on stage %r" %
                                (project, self.name))
        # since this is a mirror, we only have the simple links and no
        # metadata, so only delete the files and keep the simple links
        # for the possibility to re-download a release
        (is_expired, links, cache_serial) = self._load_cache_links(project)
        if links is not None:
            entries = list(self._entry_from_href(x[1]) for x in links)
            entries = list(x for x in entries if x.version == version and x.file_exists())
            for entry in entries:
                entry.file_delete()

    def del_entry(self, entry, cleanup=True):
        project = entry.project
        if project is None:
            raise self.NotFound("no project set on entry %r" % entry)
        if not entry.file_exists():
            raise self.NotFound("entry has no file data %r" % entry)
        entry.delete()
        (is_expired, links, cache_serial) = self._load_cache_links(project)
        if links is not None:
            links = ensure_deeply_readonly(
                list(filter(self._is_file_cached, links)))
        if not links and cleanup:
            projects = self.key_projects.get(readonly=False)
            if project in projects:
                projects.remove(project)
                self.key_projects.set(projects)

    @property
    def cache_projectnames(self):
        """ cache for full list of projectnames. """
        # we could keep this info inside keyfs but pypi.org
        # produces a several MB list of names and it changes often which
        # would spam the database.
        try:
            return self.xom.get_singleton(self.name, "projectnames")
        except KeyError:
            cache_projectnames = ProjectNamesCache()
            self.xom.set_singleton(self.name, "projectnames", cache_projectnames)
            return cache_projectnames

    @property
    def cache_retrieve_times(self):
        """ per-xom RAM cache for keeping track when we last updated simplelinks. """
        # we could keep this info in keyfs but it would lead to a write
        # for each remote check.
        try:
            return self.xom.get_singleton(self.name, "project_retrieve_times")
        except KeyError:
            c = ProjectUpdateCache()
            self.xom.set_singleton(self.name, "project_retrieve_times", c)
            return c

    def _get_remote_projects(self):
        headers = {"Accept": "text/html"}
        response = self.httpget(
            self.mirror_url, allow_redirects=True, extra_headers=headers,
            timeout=self.timeout)
        if response.status_code != 200:
            raise self.UpstreamError("URL %r returned %s %s",
                self.mirror_url, response.status_code, response.reason)
        page = HTMLPage(response.text, response.url)
        projects = set()
        baseurl = URL(response.url)
        basehost = baseurl.replace(path='')
        for link in page.links:
            newurl = URL(link.url)
            # remove trailing slashes, so basename works correctly
            newurl = newurl.asfile()
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
        if self.offline:
            threadlog.warn("offline mode: using stale projects list")
            return self.key_projects.get()
        if not self.cache_projectnames.is_expired(self.cache_expiry):
            projects = self.cache_projectnames.get()
        else:
            # no fresh projects or None at all, let's go remote
            try:
                projects = self._get_remote_projects()
            except self.UpstreamError as e:
                threadlog.warn(
                    "upstream error (%s): using stale projects list" % e)
                return self.key_projects.get()
            else:
                old = self.cache_projectnames.get()
                if not self.cache_projectnames.exists() or old != projects:
                    self.cache_projectnames.set(projects)

                    # trigger an initial-load event on master
                    if not self.xom.is_replica():
                        # make sure we are at the current serial
                        # this avoids setting the value again when
                        # called from the notification thread
                        self.keyfs.restart_read_transaction()
                        k = self.keyfs.MIRRORNAMESINIT(user=self.username, index=self.index)
                        if k.get() == 0:
                            self.keyfs.restart_as_write_transaction()
                            k.set(1)
                else:
                    # mark current without updating contents
                    self.cache_projectnames.mark_current()

        return projects

    def is_project_cached(self, project):
        """ return True if we have some cached simpelinks information. """
        return self.key_projsimplelinks(project).exists()

    def _save_cache_links(self, project, links, requires_python, serial):
        assert links != ()  # we don't store the old "Not Found" marker anymore
        assert isinstance(serial, int)
        assert project == normalize_name(project), project
        data = {"serial": serial, "links": links, 
            "requires_python": requires_python}
        key = self.key_projsimplelinks(project)
        old = key.get()
        if old != data:
            threadlog.debug("saving changed simplelinks for %s: %s", project, data)
            key.set(data)
            # maintain list of currently cached project names to enable
            # deletion and offline mode
            self.add_project_name(project)
        # XXX if the transaction fails the links are still marked
        # as refreshed but the data was not persisted.  It's a rare
        # enough event (tm) to not worry too much, though.
        # (we can, however, easily add a
        # keyfs.tx.on_commit_success(callback) method.
        self.cache_retrieve_times.refresh(project)

    def _load_cache_links(self, project):
        is_expired, links_with_require_python, serial = True, None, -1

        cache = self.key_projsimplelinks(project).get()
        if cache:
            is_expired = self.cache_retrieve_times.is_expired(project, self.cache_expiry)
            serial = cache["serial"]
            links_with_require_python = join_requires(
                cache["links"], cache.get("requires_python", []))
            if self.offline and links_with_require_python:
                links_with_require_python = ensure_deeply_readonly(list(
                    filter(self._is_file_cached, links_with_require_python)))

        return is_expired, links_with_require_python, serial

    def _entry_from_href(self, href):
        # extract relpath from href by cutting of the hash
        relpath = re.sub(r"#.*$", "", href)
        return self.filestore.get_file_entry(relpath)

    def _is_file_cached(self, link):
        entry = self._entry_from_href(link[1])
        return entry is not None and entry.file_exists()

    def clear_simplelinks_cache(self, project):
        # we have to set to an empty dict instead of removing the key, so
        # replicas behave correctly
        self.cache_retrieve_times.expire(project)
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
        is_expired, links, cache_serial = self._load_cache_links(project)
        if self.offline and links is None:
            raise self.UpstreamError("offline mode")
        if not is_expired:
            return links

        is_retrieval_expired = self.cache_retrieve_times.is_expired(
            project, self.cache_expiry)

        if links is None and not is_retrieval_expired:
            raise self.UpstreamNotFoundError(
                "cached not found for project %s" % project)

        # get the simple page for the project
        url = self.mirror_url + project + "/"
        threadlog.debug("reading index %s", url)
        response = self.httpget(url, allow_redirects=True, timeout=self.timeout)
        if response.status_code != 200:
            # if we have and old result, return it. While this will
            # miss the rare event of actual project deletions it allows
            # to stay resilient against server misconfigurations.
            if links is not None:
                threadlog.warn(
                    "serving stale links for %r, url %r responded %s %s",
                    project, url, response.status_code, response.reason)
                return links
            if response.status_code == 404:
                self.cache_retrieve_times.refresh(project)
                raise self.UpstreamNotFoundError(
                    "not found on GET %s" % url)

            # we don't have an old result and got a non-404 code.
            raise self.UpstreamError("%s status on GET %s" % (
                response.status_code, url))

        # pypi.org provides X-PYPI-LAST-SERIAL header in case of 200 returns.
        # devpi-master may provide a 200 but not supply the header
        # (it's really a 404 in disguise and we should change
        # devpi-server behaviour since pypi.org serves 404
        # on non-existing projects for a longer time now).
        # Returning a 200 with "no such project" was originally meant to
        # provide earlier versions of easy_install/pip to request the full
        # simple page.
        try:
            serial = int(response.headers.get(str("X-PYPI-LAST-SERIAL")))
        except (TypeError, ValueError):
            # handle missing or invalid X-PYPI-LAST-SERIAL header
            serial = -1

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
            maplink = partial(
                self.filestore.maplink,
                user=self.user.name, index=self.index, project=project)
            entries = [maplink(link) for link in releaselinks]
            links = [make_key_and_href(entry) for entry in entries]
            requires_python = [link.requires_python for link in releaselinks]
            self._save_cache_links(project, links, requires_python, serial)
            # make project appear in projects list even
            # before we next check up the full list with remote
            threadlog.info("setting projects cache for %r", project)
            self.cache_projectnames.get_inplace().add(project)
            return join_requires(links, requires_python)

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
            if self.keyfs.wait_tx_serial(devpi_serial, timeout=self.timeout):
                threadlog.debug("get_simplelinks pypi: finished waiting for devpi_serial %r",
                                devpi_serial)
                # XXX raise TransactionRestart to get a consistent clean view
                self.keyfs.restart_read_transaction()
                is_expired, links, cache_serial = self._load_cache_links(project)
            if links is not None:
                self.cache_retrieve_times.refresh(project)
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
        try:
            self.get_simplelinks_perstage(project)
        except self.UpstreamNotFoundError:
            return False
        return True

    def list_versions_perstage(self, project):
        try:
            return set(x.get_eggfragment_or_version()
                       for x in map(SimplelinkMeta, self.get_simplelinks_perstage(project)))
        except self.UpstreamNotFoundError:
            return []

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


class ProjectNamesCache:
    """ Helper class for maintaining project names from a mirror. """
    def __init__(self):
        self._timestamp = -1
        self._data = set()

    def exists(self):
        return self._timestamp != -1

    def is_expired(self, expiry_time):
        return (time.time() - self._timestamp) >= expiry_time

    def get(self):
        """ Get a copy of the cached data. """
        return set(self._data)

    def get_inplace(self):
        """ Get cached data in-place. """
        return self._data

    def set(self, data):
        """ Set data and update timestamp. """
        if data is not self._data:
            self._data = data.copy()
        self.mark_current()

    def mark_current(self):
        self._timestamp = time.time()


class ProjectUpdateCache:
    """ Helper class to manage when we last updated something project specific. """
    def __init__(self):
        self._project2time = {}

    def is_expired(self, project, expiry_time):
        t = self._project2time.get(project)
        if t is not None:
            return (time.time() - t) >= expiry_time
        return True

    def get_timestamp(self, project):
        return self._project2time.get(project, 0)

    def refresh(self, project):
        self._project2time[project] = time.time()

    def expire(self, project):
        self._project2time.pop(project, None)
