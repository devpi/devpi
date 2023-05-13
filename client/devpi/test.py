
from __future__ import with_statement
import re
import shlex
import hashlib
import py
from devpi_common.archive import Archive
from devpi_common.metadata import parse_requirement
import json
import sys

from devpi_common.url import URL
from devpi_common.metadata import get_sorted_versions
from devpi_common.viewhelp import ViewLinkStore


class DevIndex:
    def __init__(self, hub, rootdir, current):
        self.rootdir = rootdir
        self.current = current
        self.hub = hub
        self.dir_download = self.rootdir.mkdir("downloads")

    def download_and_unpack(self, versioninfo, link):
        basic_auth = self.hub.current.get_basic_auth(link.href)
        if basic_auth:
            auth_url = link.href
            url = auth_url
        else:
            auth_url = self.hub.current.add_auth_to_url(link.href)
            url = auth_url.replace(password="****")
        r = self.hub.http.get(auth_url,
                              auth=basic_auth,
                              cert=self.hub.current.get_client_cert(url))
        if r.status_code != 200:
            self.hub.fatal("could not receive", url)
        content = r.content
        assert content

        self.hub.info("received", url)
        if hasattr(link, "md5"):
            md5 = hashlib.md5()
            md5.update(content)
            digest = md5.hexdigest()
            assert digest == link.md5, (digest, link.md5)
        basename = URL(url).basename

        path_archive = self.dir_download.join(basename)
        with path_archive.open("wb") as f:
            f.write(content)
        pkg = UnpackedPackage(
            self.hub, self.rootdir, path_archive, versioninfo, link)
        pkg.unpack()
        return pkg

    def get_matching_versioninfo(self, pkgname, indexname):
        req = parse_requirement(pkgname)
        projurl = self.current.get_project_url(
            req.project_name, indexname=indexname).url
        r = self.hub.http_api("get", projurl, fatal=False)
        if r.status_code != 200:
            return
        for version in get_sorted_versions(r.result):
            if version not in req:
                continue
            return ViewLinkStore(projurl, r.result[version])

    def runtox(self, link, pkg, sdist_pkg=None, upload_tox_results=True):
        jsonreport = pkg.rootdir.join("toxreport.json")
        path_archive = pkg.path_archive
        tox_path = self.hub.current.getvenvbin(
            "tox", venvdir=self.hub.venv, glob=True)
        if not tox_path:
            # try outside of venv
            tox_path = py.path.local.sysfind("tox")
        if not tox_path:
            self.hub.fatal("no tox binary found")
        toxcmd = [
            str(tox_path),
            "--installpkg", str(path_archive),
            "--recreate",
            "--result-json", str(jsonreport),
        ]
        if self.current.simpleindex != self.current.simpleindex_auth:
            self.hub.info("Using existing basic auth for '%s'." %
                          self.current.simpleindex)
            self.hub.warn("With pip < 19.3 the password might be exposed "
                          "in the JSON report!")
            simpleindex = self.current.simpleindex_auth
        else:
            simpleindex = self.hub.current.add_auth_to_url(
                self.current.simpleindex)

        if sdist_pkg is None:
            sdist_pkg = pkg
        toxcmd.extend(self.get_tox_args(unpack_path=sdist_pkg.path_unpacked))

        ret = 0
        with sdist_pkg.path_unpacked.as_cwd():
            try:
                self.hub.popen_check(
                    toxcmd,
                    stdout=sys.stdout,
                    stderr=sys.stderr,
                    extraenv={
                        "PIP_INDEX_URL": simpleindex})
            except SystemExit as e:
                ret = e.args[0]

        if ret != 2 and upload_tox_results:
            jsondata = json.load(jsonreport.open("r"))
            url = URL(link.href)
            post_tox_json_report(self.hub, url.url_nofrag, jsondata)
        if ret != 0:
            self.hub.error("tox command failed", ret)
            return 1
        return 0

    def get_tox_args(self, unpack_path):
        hub = self.hub
        args = self.hub.args
        toxargs = []
        if args.toxenv is not None:
            toxargs.append("-e" + args.toxenv)
        if args.toxini:
            ini = hub.get_existing_file(args.toxini)
        elif unpack_path.join("tox.ini").exists():
            ini = hub.get_existing_file(unpack_path.join("tox.ini"))
        elif args.fallback_ini:
            ini = hub.get_existing_file(args.fallback_ini)
        else:
            hub.fatal("no tox.ini file found in %s" % unpack_path)
        toxargs.extend(["-c", str(ini)])
        if args.toxargs:
            toxargs.extend(shlex.split(args.toxargs))
        return toxargs


def post_tox_json_report(hub, href, jsondata):
    hub.line("posting tox result data to %s" % href)
    r = hub.http_api("post", href, kvdict=jsondata)
    if r.status_code == 200:
        hub.info("successfully posted tox result data")
    else:
        hub.error("could not post tox result data to: %s" % href)


class UnpackedPackage:
    def __init__(self, hub, rootdir, path_archive, versioninfo, link):
        self.hub = hub
        basename = link.basename
        if basename.endswith(".whl"):
            rootdir = rootdir.join(basename)
        elif basename.endswith(".tar.gz") or basename.endswith(".tgz"):
            rootdir = rootdir.join("targz")
        elif basename.endswith(".zip"):
            rootdir = rootdir.join("zip")
        assert not rootdir.check(), rootdir
        self.rootdir = rootdir
        self.path_archive = path_archive
        self.versioninfo = versioninfo
        self.link = link

    def unpack(self):
        self.hub.info("unpacking", self.path_archive, "to", str(self.rootdir))
        with Archive(self.path_archive) as archive:
            archive.extract(self.rootdir)
        pkgname = self.versioninfo.versiondata['name']
        version = self.versioninfo.versiondata['version']
        if self.link.basename.endswith(".whl"):
            inpkgdir = self.rootdir
        else:
            inpkgdir = self.rootdir.join("%s-%s" %(pkgname, version))
            if not inpkgdir.check():
                # sometimes dashes are replaced by underscores,
                # for example the source releases of argon2_cffi
                inpkgdir = self.rootdir.join(
                    "%s-%s" % (pkgname.replace('-', '_'), version))
        if not inpkgdir.check():
            self.hub.fatal("Couldn't find unpacked package in", inpkgdir)
        self.path_unpacked = inpkgdir


def find_sdist_and_wheels(hub, links, universal_only=True):
    sdist_links = []
    wheel_links = []
    for link in links:
        bn = link.basename
        if bn.endswith(".tar.gz"):
            sdist_links.insert(0, link)
        elif bn.endswith(".zip"):
            sdist_links.append(link)
        elif bn.endswith(".whl"):
            if universal_only and not bn.endswith("py2.py3-none-any.whl"):
                hub.warn("only universal wheels supported, found", bn)
                continue
            wheel_links.append(link)
    if not sdist_links:
        hub.fatal("need at least one sdist distribution")
    return sdist_links, wheel_links


def prepare_toxrun_args(dev_index, versioninfo, sdist_links, wheel_links, select=None):
    toxrunargs = []
    for sdist_link in sdist_links:
        sdist_pkg = dev_index.download_and_unpack(versioninfo, sdist_link)
        toxrunargs.append((sdist_link, sdist_pkg))
    # for testing wheels we need an sdist because wheels
    # typically don't contain test or tox.ini files
    if select:
        select = re.compile(select)
    for wheel_link in wheel_links:
        if select and not select.search(wheel_link.basename):
            # skip not matching
            continue
        wheel_pkg = dev_index.download_and_unpack(versioninfo, wheel_link)
        toxrunargs.append((wheel_link, wheel_pkg, toxrunargs[0][1]))
    if select:
        # filter whole list, in case the sdist is filtered out as well
        toxrunargs = [
            x
            for x in toxrunargs
            if select.search(x[0].basename)]
    return toxrunargs


def main(hub, args):
    current = hub.current
    index = args.index
    if index:
        if index.startswith(('http:', 'https:')):
            current = hub.current.switch_to_temporary(hub, index)
            index = None
        elif index.count("/") > 1:
            hub.fatal("index %r not of form URL, USER/NAME or NAME" % index)
    with hub.workdir(prefix="devpi-test-") as tmpdir:
        devindex = DevIndex(hub, tmpdir, current)
        for pkgspec in args.pkgspec:
            versioninfo = devindex.get_matching_versioninfo(pkgspec, index)
            if not versioninfo:
                hub.fatal("could not find/receive links for", pkgspec)
            links = versioninfo.get_links("releasefile")
            if not links:
                hub.fatal("could not find/receive links for", pkgspec)

            universal_only = args.select is None
            sdist_links, wheel_links = find_sdist_and_wheels(
                hub, links, universal_only=universal_only)
            toxrunargs = prepare_toxrun_args(
                devindex, versioninfo, sdist_links, wheel_links,
                select=args.select)
            all_ret = 0
            if args.list:
                hub.info("would test:")
            for toxargs in toxrunargs:
                if args.list:
                    hub.info("  ", toxargs[0].href)
                    continue
                ret = devindex.runtox(
                    *toxargs, upload_tox_results=args.upload_tox_results)
                if ret != 0:
                    all_ret = 1
        return all_ret
