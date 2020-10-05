
from __future__ import with_statement
import os
import re
import shlex
import hashlib
import pkg_resources
import py
from devpi_common.archive import Archive
import json
import tox

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
        url = link.href
        r = self.hub.http.get(url,
                              auth=self.hub.current.get_basic_auth(url),
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
            #self.hub.info("verified md5 ok", link.md5)
        basename = URL(url).basename

        path_archive = self.dir_download.join(basename)
        with path_archive.open("wb") as f:
            f.write(content)
        pkg = UnpackedPackage(
            self.hub, self.rootdir, path_archive, versioninfo, link)
        pkg.unpack()
        return pkg

    def get_matching_versioninfo(self, pkgname, indexname):
        req = next(pkg_resources.parse_requirements(pkgname))
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
        toxargs = [
            "--installpkg", str(path_archive),
            "-i ALL=%s" % str(self.current.simpleindex_auth),
            "--recreate",
            "--result-json", str(jsonreport),
        ]
        if self.current.simpleindex != self.current.simpleindex_auth:
            self.hub.info("Using existing basic auth for '%s'." %
                          self.current.simpleindex)
            self.hub.warn("The password will be available unencrypted in the "
                          "JSON report!")

        if sdist_pkg is None:
            sdist_pkg = pkg
        toxargs.extend(self.get_tox_args(unpack_path=sdist_pkg.path_unpacked))

        with sdist_pkg.path_unpacked.as_cwd():
            self.hub.info("%s$ tox %s" % (os.getcwd(), " ".join(toxargs)))
            toxrunner = self.get_tox_runner()
            try:
                ret = toxrunner(toxargs)
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

    def get_tox_runner(self):
        if self.hub.args.detox:
            try:
                from detox.cli import main as detox_main
            except ImportError:
                from detox.main import main as detox_main
            return detox_main
        else:
            return tox.cmdline

    def get_tox_args(self, unpack_path):
        hub = self.hub
        args = self.hub.args
        toxargs = []
        if args.venv is not None:
            toxargs.append("-e" + args.venv)
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
    for wheel_link in wheel_links:
        wheel_pkg = dev_index.download_and_unpack(versioninfo, wheel_link)
        toxrunargs.append((wheel_link, wheel_pkg, toxrunargs[0][1]))
    if select:
        toxrunargs = [
            x
            for x in toxrunargs
            if re.search(select, x[0].basename)]
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
    tmpdir = py.path.local.make_numbered_dir("devpi-test", keep=3)
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
            devindex, versioninfo, sdist_links, wheel_links, select=args.select)
        all_ret = 0
        if args.list:
            hub.info("would test:")
        for toxargs in toxrunargs:
            if args.list:
                hub.info("  ", toxargs[0].href)
                continue
            ret = devindex.runtox(*toxargs, upload_tox_results=args.upload_tox_results)
            if ret != 0:
                all_ret = 1
    return all_ret
