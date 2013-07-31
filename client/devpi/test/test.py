
from __future__ import with_statement
import os, sys
import hashlib
import mimetypes
import posixpath
import py
import devpi
import argparse
import pkg_resources
import archive

from devpi.util import url as urlutil
from devpi.util import version as verlib
from devpi.util import pypirc
from devpi.remoteindex import RemoteIndex

import requests

def setenv_devpi(hub, env, posturl, packageurl, packagemd5):
    if not packagemd5:
        packagemd5 = ""
    if sys.version_info[0] < 3:
        posturl = posturl.encode("utf8")
        packageurl = packageurl.encode("utf8")
        packagemd5 = packagemd5.encode("utf8")
    env["DEVPY_POSTURL"] = posturl.encode("utf8")
    env["DEVPY_PACKAGEURL"] = packageurl.encode("utf8")
    env["DEVPY_PACKAGEMD5"] = (packagemd5 or "").encode("utf8")
    for name in env:
        if name.startswith("DEVPY"):
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
            content = self.remoteindex.getcontent(link.href)
        except self.remoteindex.ReceiveError:
            self.hub.fatal("could not receive", link.href)

        self.hub.info("received", link.href)
        if hasattr(link, "md5"):
            md5 = hashlib.md5()
            md5.update(content)
            assert md5.hexdigest() == link.md5
            self.hub.info("verified md5 ok", link.md5)
        path_archive = self.dir_download.join(link.basename)
        with path_archive.open("wb") as f:
            f.write(content)
        pkg = UnpackedPackage(self.hub, self.rootdir, path_archive, link)
        pkg.unpack()
        link.pkg = pkg

    def getbestlink(self, pkgname):
        #req = pkg_resources.parse_requirements(pkgspec)[0]
        return self.remoteindex.getbestlink(pkgname)

    def runtox(self, link, Popen, venv=None):
        path_archive = link.pkg.path_archive

        # the env var is picked up by pytest-devpi plugin
        env = os.environ.copy()
        #setenv_devpi(self.hub, env, posturl=self.current.resultlog,
        #                  packageurl=link.href,
        #                  packagemd5=link.md5)
        toxargs = ["tox", "--installpkg", str(path_archive),
                   "-i ALL=%s" % self.current.simpleindex,
                   "-v",
        ]
        if venv is not None:
            toxargs.append("-e" + venv)

        self.hub.info("%s$ %s" %(link.pkg.path_unpacked, " ".join(toxargs)))
        popen = Popen(toxargs, cwd=str(link.pkg.path_unpacked), env=env)
        popen.communicate()
        if popen.returncode != 0:
            self.hub.error("tox command failed", popen.returncode)
            return 1
        return 0


class UnpackedPackage:
    def __init__(self, hub, rootdir, path_archive, link):
        self.hub = hub
        self.rootdir = rootdir
        self.path_archive = path_archive
        self.link = link

    def unpack(self):
        self.hub.info("unpacking", self.path_archive, "to", str(self.rootdir))
        archive.extract(str(self.path_archive), to_path=str(self.rootdir))
        pkgname, version = verlib.guess_pkgname_and_version(self.link.basename)
        subdir = "%s-%s" %(pkgname, version)
        inpkgdir = self.rootdir.join(subdir)
        assert inpkgdir.check(), inpkgdir
        self.path_unpacked = inpkgdir


def main(hub, args):
    hub.require_valid_current_with_index()
    tmpdir = py.path.local.make_numbered_dir("devpi-test", keep=3)
    current = hub.current
    if not current.exists():
        hub.fatal("no api configuration found")
    devindex = DevIndex(hub, tmpdir, current)
    link = devindex.getbestlink(args.pkgspec[0])
    if not link:
        hub.fatal("could not find/receive link")
    devindex.download_and_unpack(link)
    ret = devindex.runtox(link, Popen=hub.Popen, venv=args.venv)
    return ret
