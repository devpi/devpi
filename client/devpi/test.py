
from __future__ import with_statement
import os
import sys
import shlex
import hashlib
import pkg_resources
import py
from devpi_common.archive import Archive
import json
import tox

from devpi_common.url import URL
from devpi_common.metadata import get_sorted_versions, splitbasename
from devpi_common.viewhelp import ViewLinkStore


def setenv_devpi(hub, env, posturl, packageurl, packagemd5):
    if not packagemd5:
        packagemd5 = ""
    if sys.version_info[0] < 3:
        posturl = posturl.encode("utf8")
        packageurl = packageurl.encode("utf8")
        packagemd5 = packagemd5.encode("utf8")
    env["DEVPI_POSTURL"] = posturl.encode("utf8")
    env["DEVPI_PACKAGEURL"] = packageurl.encode("utf8")
    env["DEVPI_PACKAGEMD5"] = (packagemd5 or "").encode("utf8")
    for name in env:
        if name.startswith("DEVPI"):
            hub.debug("setenv_devpi %s %s", name, env[name])


class DevIndex:
    def __init__(self, hub, rootdir, current):
        self.rootdir = rootdir
        self.current = current
        self.hub = hub
        self.dir_download = self.rootdir.mkdir("downloads")

    def download_and_unpack(self, versioninfo, link):
        url = link.href
        r = self.hub.http.get(url)
        if r.status_code != 200:
            self.hub.fatal("could not receive", url)
        content = r.content

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

    def getbest(self, pkgname):
        req = next(pkg_resources.parse_requirements(pkgname))
        projurl = self.hub.current.index_url.asdir().joinpath(req.project_name).url
        r = self.hub.http_api("get", projurl)
        for version in get_sorted_versions(r.result):
            if version not in req:
                continue
            versioninfo = ViewLinkStore(projurl, r.result[version])
            link = versioninfo.get_link('releasefile')
            if link:
                return (versioninfo, link)
        return (None, None)

    def runtox(self, link, pkg):
        jsonreport = pkg.rootdir.join("toxreport.json")
        path_archive = pkg.path_archive
        toxargs = ["--installpkg", str(path_archive),
                   "-i ALL=%s" % str(self.current.simpleindex),
                   "--result-json", str(jsonreport),
        ]
        unpack_path = pkg.path_unpacked

        toxargs.extend(self.get_tox_args(unpack_path=unpack_path))
        with pkg.path_unpacked.as_cwd():
            self.hub.info("%s$ tox %s" %(os.getcwd(), " ".join(toxargs)))
            try:
                ret = tox.cmdline(toxargs)
            except SystemExit as e:
                ret = e.args[0]
        if ret != 2:
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
        subdir = "%s-%s" % (pkgname, version)
        inpkgdir = self.rootdir.join(subdir)
        assert inpkgdir.check(), inpkgdir
        self.path_unpacked = inpkgdir


def main(hub, args):
    current = hub.require_valid_current_with_index()
    tmpdir = py.path.local.make_numbered_dir("devpi-test", keep=3)
    devindex = DevIndex(hub, tmpdir, current)
    versioninfo, link = devindex.getbest(args.pkgspec[0])
    if not link:
        hub.fatal("could not find/receive link")
    pkg = devindex.download_and_unpack(versioninfo, link)
    ret = devindex.runtox(link, pkg)
    return ret
