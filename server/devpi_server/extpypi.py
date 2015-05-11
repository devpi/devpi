"""

Implementation of the database layer for PyPI Package serving and
toxresult storage.

"""

from __future__ import unicode_literals
try:
    import xmlrpc.client as xmlrpc
except ImportError:
    import xmlrpclib as xmlrpc

import py

from devpi_common.vendor._pip import HTMLPage

from devpi_common.url import URL
from devpi_common.metadata import BasenameMeta
from devpi_common.metadata import is_archive_of_project, splitbasename
from devpi_common.types import ensure_unicode_keys
from devpi_common.validation import normalize_name, ensure_unicode
from devpi_common.request import new_requests_session

from . import __version__ as server_version
from .model import BaseStage
from .keyfs import load_from_file, dump_to_file
from .log import threadlog, thread_current_log, thread_push_log


class IndexParser:

    def __init__(self, projectname):
        self.projectname = normalize_name(projectname)
        self.basename2link = {}
        self.crawllinks = set()
        self.egglinks = []

    def _mergelink_ifbetter(self, newurl):
        entry = self.basename2link.get(newurl.basename)
        if entry is None or (not entry.hash_spec and newurl.hash_spec):
            self.basename2link[newurl.basename] = newurl
            threadlog.debug("adding link %s", newurl)
        else:
            threadlog.debug("ignoring candidate link %s", newurl)

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
                if not normalize_name(eggfragment).startswith(
                    self.projectname):
                    threadlog.debug("skip egg link %s (projectname: %s)",
                              newurl, self.projectname)
                    continue
                if newurl.basename:
                    # XXX seems we have to maintain a particular
                    # order to keep pip/easy_install happy with some
                    # packages (e.g. nose)
                    if newurl not in self.egglinks:
                        self.egglinks.insert(0, newurl)
                else:
                    threadlog.warn("cannot handle egg directory link (svn?) "
                              "skipping: %s (projectname: %s)",
                              newurl, self.projectname)
                continue
            if is_archive_of_project(newurl, self.projectname):
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
    projectname = disturl.basename or disturl.parentbasename
    parser = IndexParser(projectname)
    parser.parse_index(disturl, html, scrape=scrape)
    return parser

class XMLProxy(object):
    def __init__(self, url):
        self._url = url
        self._session = new_requests_session(agent=("server", server_version))
        self._session.headers["content-type"] = "text/xml"
        self._session.headers["Accept"] = "text/xml"

    def list_packages_with_serial(self):
        return self._execute("list_packages_with_serial")

    def changelog_since_serial(self, serial):
        return self._execute("changelog_since_serial", serial)

    def _execute(self, method, *args):
        payload = xmlrpc.dumps(args, method)
        threadlog.debug("-> %s%s" %(method, args))
        try:
            reply = self._session.post(self._url, data=payload, stream=False)
        except Exception as exc:
            threadlog.warn("%s: error %s with remote %s",
                           method, exc, self._url)
            return None
        if reply.status_code != 200:
            threadlog.warn("%s: status_code %s with remote %s", method,
                     reply.status_code, self._url)
            return None
        res = xmlrpc.loads(reply.content)[0][0]
        if isinstance(res, (list, dict)) and len(res) > 3:
            repr_res = "%r with %s entries" %(type(res).__name__, len(res))
        else:
            repr_res = repr(res)
        threadlog.debug("<- %s%s: %s" %(method, args, repr_res))
        return res


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
    username = "root"
    index = "pypi"
    name = "root/pypi"
    ixconfig = {"bases": (), "volatile": False, "type": "mirror",
                "pypi_whitelist": (), "custom_data": "",
                "acl_upload": ["root"]}

    def __init__(self, xom):
        self.keyfs = xom.keyfs
        self.httpget = xom.httpget
        self.filestore = xom.filestore
        self.pypimirror = xom.pypimirror
        self.xom = xom
        if xom.is_replica():
            url = xom.config.master_url
            self.PYPIURL_SIMPLE = url.joinpath("root/pypi/+simple/").url
        else:
            self.PYPIURL_SIMPLE = PYPIURL_SIMPLE

    def list_projectnames_perstage(self):
        """ return list of all projects served through the mirror. """
        return set(self.pypimirror.name2serials)

    def _dump_project_cache(self, projectname, entries, serial):
        normname = normalize_name(projectname)
        dumplist = [(entry.relpath, entry.hash_spec, entry.eggfragment)
                            for entry in entries]
        data = {"serial": serial,
                "latest_serial": serial,
                "entrylist": dumplist,
                "projectname": projectname}
        threadlog.debug("saving data for %s: %s", projectname, data)
        self.keyfs.PYPILINKS(name=normname).set(data)
        return list(self._make_elinks(projectname, data["entrylist"]))

    def _load_project_cache(self, projectname):
        normname = normalize_name(projectname)
        data = self.keyfs.PYPILINKS(name=normname).get()
        #log.debug("load data for %s: %s", projectname, data)
        return data

    def _load_cache_links(self, projectname):
        cache = self._load_project_cache(projectname)
        if cache:
            return (cache["serial"] >= cache["latest_serial"],
                   list(self._make_elinks(projectname, cache["entrylist"])))
        return True, None

    def _make_elinks(self, projectname, data):
        from .model import ELink
        for relpath, hash_spec, eggfragment in data:
            linkdict = {"entrypath": relpath, "hash_spec": hash_spec,
                        "eggfragment": eggfragment}
            version = "XXX"
            try:
                name, version = splitbasename(relpath)[:2]
            except ValueError:
                pass
            yield ELink(self.filestore, linkdict, projectname, version)

    def clear_cache(self, projectname):
        normname = normalize_name(projectname)
        # we have to set to an empty dict instead of removing the key, so
        # replicas behave correctly
        self.keyfs.PYPILINKS(name=normname).set({})
        threadlog.debug("cleared cache for %s", projectname)

    def get_releaselinks_perstage(self, projectname):
        """ return all releaselinks from the index and referenced scrape
        pages, returning cached entries if we have a recent enough
        request stored locally.

        Raise UpstreamError if the pypi server cannot be reached or
        does not return a fresh enough page although we know it must
        exist.
        """
        projectname = self.get_projectname_perstage(projectname)
        if projectname is None:
            return []
        is_fresh, links = self._load_cache_links(projectname)
        if links is not None and is_fresh:
            return links

        # get the simple page for the project
        url = self.PYPIURL_SIMPLE + projectname + "/"
        threadlog.debug("visiting index %s", url)
        response = self.httpget(url, allow_redirects=True)
        if response.status_code != 200:
            # if we have an old version, return it instead of erroring out
            if links is not None:
                threadlog.error("serving stale links for %r, upstream not reachable",
                                projectname)
                return links
            # XXX it's not correct to return UpstreamError in all cases
            # if indeed the project was deleted but that fact
            # is not yet properly processed
            raise self.UpstreamError("%s status on GET %s" %
                                     (response.status_code, url))

        if self.xom.is_replica():
            # XXX this code path is not currently tested, handle with care!
            # we have already triggered the master above
            # and now need to wait until the parsed new links are
            # transferred back to the replica
            devpi_serial = int(response.headers["X-DEVPI-SERIAL"])
            self.keyfs.notifier.wait_tx_serial(devpi_serial)
            # XXX raise TransactionRestart to get a consistent clean view
            self.keyfs.commit_transaction_in_thread()
            self.keyfs.begin_transaction_in_thread()
            is_fresh, links = self._load_cache_links(projectname)
            if links is not None:
                return links
            raise self.UpstreamError("no cache links from master for %s" %
                                     projectname)

        # check that we got a fresh enough page
        serial = int(response.headers["X-PYPI-LAST-SERIAL"])
        newest_serial = self.pypimirror.name2serials.get(projectname, -1)
        if serial < newest_serial:
            raise self.UpstreamError(
                        "%s: pypi returned serial %s, expected %s",
                        projectname, serial, newest_serial)

        threadlog.debug("%s: got response with serial %s" %
                  (projectname, serial))


        # check returned url has the same normalized name
        ret_projectname = response.url.strip("/").split("/")[-1]
        assert normalize_name(projectname) == normalize_name(ret_projectname)


        # parse simple index's link and perform crawling
        assert response.text is not None, response.text
        result = parse_index(response.url, response.text)
        perform_crawling(self, result)
        releaselinks = list(result.releaselinks)

        self.keyfs.restart_as_write_transaction()

        # compute release link entries and cache according to serial
        entries = [self.filestore.maplink(link) for link in releaselinks]
        return self._dump_project_cache(projectname, entries, serial)

    def get_projectname_perstage(self, name):
        return self.pypimirror.get_registered_name(name)

    def list_versions_perstage(self, projectname):
        versions = set()
        for link in self.get_releaselinks_perstage(projectname):
            basename = link.basename
            if link.eggfragment:
                version = "egg=" + link.eggfragment
            else:
                version = BasenameMeta(basename).version
            versions.add(version)
        return versions

    def get_versiondata_perstage(self, projectname, version):
        links = self.get_releaselinks_perstage(projectname)
        verdata = {}
        for link in links:
            basename = link.basename
            if link.eggfragment:
                link_version = "egg=" + link.eggfragment
            else:
                link_version = BasenameMeta(basename).version
            if version != link_version:
                continue
            if not verdata:
                verdata['name'] = projectname
                verdata['version'] = version
            links = verdata.setdefault("+elinks", [])
            links.append({"rel": "releasefile", "entrypath": link.entrypath})
        return verdata


class PyPIMirror:
    def __init__(self, xom):
        self.xom = xom
        self.keyfs = keyfs = xom.keyfs
        self.path_name2serials = str(
            keyfs.basedir.join(PyPIStage.name, ".name2serials"))

    def get_registered_name(self, name):
        norm_name = normalize_name(name)
        name = self.normname2name.get(norm_name, norm_name)
        if name in self.name2serials:
            return name

    def init_pypi_mirror(self, proxy):
        """ initialize pypi mirror if no mirror state exists. """
        self.name2serials = self.load_name2serials(proxy)
        # create a mapping of normalized name to real name
        self.normname2name = d = dict()
        for name in self.name2serials:
            norm = normalize_name(name)
            assert py.builtin._istext(norm)
            assert py.builtin._istext(name)
            if norm != name:
                d[norm] = name

    def load_name2serials(self, proxy):
        name2serials = load_from_file(self.path_name2serials, {})
        if name2serials:
            threadlog.info("reusing already cached name/serial list")
            ensure_unicode_keys(name2serials)
        else:
            threadlog.info("retrieving initial name/serial list")
            name2serials = proxy.list_packages_with_serial()
            if name2serials is None:
                from devpi_server.main import fatal
                fatal("mirror initialization failed: "
                      "pypi.python.org not reachable")
            ensure_unicode_keys(name2serials)

            dump_to_file(name2serials, self.path_name2serials)
            # trigger anything (e.g. web-search indexing) that wants to
            # look at the initially loaded serials
            if not self.xom.is_replica():
                with self.xom.keyfs.transaction(write=True):
                    with self.xom.keyfs.PYPI_SERIALS_LOADED.update():
                        pass
        return name2serials

    def set_project_serial(self, name, serial):
        """ set the current serial and update projectname normalization table.

        Usually ``name`` is a "realname" not a normalized name.
        But you can pass in a normalized name if the project
        is already known in which case we derive the real name
        automatically.
        """
        n = normalize_name(name)
        if n in self.normname2name:
            name = self.normname2name[n]

        if serial is None:
            del self.name2serials[name]
            self.normname2name.pop(n, None)
        else:
            self.name2serials[name] = serial
            if n != name:
                self.normname2name[n] = name
        return n

    def thread_run(self, proxy):
        log = thread_push_log("[MIR]")
        log.info("changelog/update tasks starting")
        while 1:
            # get changes since the maximum serial we are aware of
            current_serial = max(itervalues(self.name2serials))
            changelog = proxy.changelog_since_serial(current_serial)
            if changelog:
                with self.keyfs.transaction(write=True):
                    self.process_changelog(changelog)
            self.thread.sleep(self.xom.config.args.refresh)

    def process_changelog(self, changelog):
        changed = set()
        log = thread_current_log()
        for x in changelog:
            name, version, action, date, serial = x
            # XXX remove names if action == "remove" and version is None
            name = ensure_unicode(name)
            normname = self.set_project_serial(name, serial)
            changed.add(normname)
            key = self.keyfs.PYPILINKS(name=normname)
            cache = key.get()
            if cache:
                if cache["latest_serial"] >= serial:  # should this happen?
                    return  # the cached serial is new enough
                cache["latest_serial"] = serial
                key.set(cache)
                log.debug("set latest_serial of %s to %s",
                          normname, serial)
            #else:
            #    log.debug("no cache found for %s" % name)
        # XXX include name2serials writing into the ongoing transaction
        # as an external rename (not managed through keyfs)
        if self.name2serials:
            dump_to_file(self.name2serials, self.path_name2serials)

        log.debug("processed changelog of size %d: %s" %(
                  len(changelog), ",".join(changed)))





PYPIURL_SIMPLE = "https://pypi.python.org/simple/"
PYPIURL = "https://pypi.python.org/"

def itervalues(d):
    return getattr(d, "itervalues", d.values)()
def iteritems(d):
    return getattr(d, "iteritems", d.items)()
