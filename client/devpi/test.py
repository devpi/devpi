
from __future__ import with_statement
import os
import sys
import shlex
import hashlib
import py
from devpi_common.archive import Archive
import json
import tox

from devpi_common.url import URL
from devpi_common.metadata import splitbasename
from devpi.remoteindex import RemoteIndex

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
        self.remoteindex = RemoteIndex(current)
        self.dir_download = self.rootdir.mkdir("downloads")

    def download_and_unpack(self, link):
        try:
            content = self.remoteindex.getcontent(link.url, bytes=True)
        except self.remoteindex.ReceiveError:
            self.hub.fatal("could not receive", link.url)

        self.hub.info("received", link.url)
        if hasattr(link, "md5"):
            md5 = hashlib.md5()
            md5.update(content)
            digest = md5.hexdigest()
            assert digest == link.md5, (digest, link.md5)
            #self.hub.info("verified md5 ok", link.md5)
        basename = URL(link.url).basename
        path_archive = self.dir_download.join(basename)
        with path_archive.open("wb") as f:
            f.write(content)
        pkg = UnpackedPackage(self.hub, self.rootdir, path_archive, link)
        pkg.unpack()
        link.pkg = pkg

    def getbestlink(self, pkgname):
        #req = pkg_resources.parse_requirements(pkgspec)[0]
        return self.remoteindex.getbestlink(pkgname)

    def runtox(self, link):
        # publishing some infos to the commands started by tox
        #setenv_devpi(self.hub, env, posturl=self.current.resultlog,
        #                  packageurl=link.url,
        #                  packagemd5=link.md5)
        jsonreport = link.pkg.rootdir.join("toxreport.json")
        path_archive = link.pkg.path_archive
        toxargs = ["--installpkg", str(path_archive),
                   "-i ALL=%s" % str(self.current.simpleindex),
                   "--result-json", str(jsonreport),
        ]
        unpack_path = link.pkg.path_unpacked

        toxargs.extend(self.get_tox_args(unpack_path=unpack_path))
        with link.pkg.path_unpacked.as_cwd():
            self.hub.info("%s$ tox %s" %(os.getcwd(), " ".join(toxargs)))
            try:
                ret = tox.cmdline(toxargs)
            except SystemExit as e:
                ret = e.args[0]
        if ret != 2:
            jsondata = json.load(jsonreport.open("r"))
            post_tox_json_report(self.hub,
                                 self.hub.current.resultlog, jsondata)
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
    def __init__(self, hub, rootdir, path_archive, link):
        self.hub = hub
        self.rootdir = rootdir
        self.path_archive = path_archive
        self.link = link

    def unpack(self):
        self.hub.info("unpacking", self.path_archive, "to", str(self.rootdir))
        with Archive(self.path_archive) as archive:
            archive.extract(self.rootdir)
        basename = URL(self.link.url).basename
        pkgname, version = splitbasename(basename)[:2]
        subdir = "%s-%s" %(pkgname, version)
        inpkgdir = self.rootdir.join(subdir)
        assert inpkgdir.check(), inpkgdir
        self.path_unpacked = inpkgdir


def main(hub, args):
    current = hub.require_valid_current_with_index()
    tmpdir = py.path.local.make_numbered_dir("devpi-test", keep=3)
    devindex = DevIndex(hub, tmpdir, current)
    link = devindex.getbestlink(args.pkgspec[0])
    if not link:
        hub.fatal("could not find/receive link")
    devindex.download_and_unpack(link)
    ret = devindex.runtox(link)
    return ret
