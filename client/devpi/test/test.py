
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
from devpi import log

pytestpluginpath = py.path.local(devpi.__file__).dirpath(
        "test", "inject", "pytest_devpi.py")

import requests

def setenv_devpi(env, posturl, packageurl, packagemd5):
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
            log.debug("setenv_devpi", name, env[name])


class DevIndex:
    def __init__(self, rootdir, config):
        self.rootdir = rootdir
        self.config = config
        self.remoteindex = RemoteIndex(config)
        self.dir_download = self.rootdir.mkdir("downloads")

    def download_and_unpack(self, link):
        try:
            content = self.remoteindex.getcontent(link.href)
        except self.remoteindex.ReceiveError:
            log.fatal("could not receive", link.href)

        log.info("received", link.href)
        if hasattr(link, "md5"):
            md5 = hashlib.md5()
            md5.update(content)
            assert md5.hexdigest() == link.md5
            log.info("verified md5 ok", link.md5)
        path_archive = self.dir_download.join(link.basename)
        with path_archive.open("wb") as f:
            f.write(content)
        pkg = UnpackedPackage(self.rootdir, path_archive, link)
        pkg.unpack()
        link.pkg = pkg

    def getbestlink(self, pkgname):
        #req = pkg_resources.parse_requirements(pkgspec)[0]
        return self.remoteindex.getbestlink(pkgname)

    def runtox(self, link, Popen, venv=None):
        path_archive = link.pkg.path_archive

        assert pytestpluginpath.check()

        # the env var is picked up by pytest-devpi plugin
        env = os.environ.copy()
        setenv_devpi(env, posturl=self.config.resultlog,
                          packageurl=link.href,
                          packagemd5=link.md5)
        # to get pytest to pick up our devpi plugin
        # XXX in the future we rather want to instruct tox to use
        # a pytest driver with our plugin enabled and maybe
        # move reporting and posting of resultlogs to tox
        env["PYTHONPATH"] = pytestpluginpath.dirname
        log.debug("setting PYTHONPATH", env["PYTHONPATH"])
        env["PYTEST_PLUGINS"] = x = pytestpluginpath.purebasename
        log.debug("setting PYTEST_PLUGINS", env["PYTEST_PLUGINS"])
        for name, val in env.items():
            assert isinstance(val, str), (name, val)
        log.debug("pytestplugin", x)
        toxargs = ["tox", "--installpkg", str(path_archive),
                   "-i ALL=%s" % self.config.simpleindex,
                   "-v",
        ]
        if venv is not None:
            toxargs.append("-e" + venv)

        log.info("%s$ %s" %(link.pkg.path_unpacked, " ".join(toxargs)))
        popen = Popen(toxargs, cwd=str(link.pkg.path_unpacked), env=env)
        popen.communicate()
        if popen.returncode != 0:
            log.error("tox command failed", popen.returncode)
            return 1
        return 0


class UnpackedPackage:
    def __init__(self, rootdir, path_archive, link):
        self.rootdir = rootdir
        self.path_archive = path_archive
        self.link = link

    def unpack(self):
        log.info("unpacking", self.path_archive, "to", str(self.rootdir))
        archive.extract(str(self.path_archive), to_path=str(self.rootdir))
        pkgname, version = verlib.guess_pkgname_and_version(self.link.basename)
        subdir = "%s-%s" %(pkgname, version)
        inpkgdir = self.rootdir.join(subdir)
        assert inpkgdir.check(), inpkgdir
        self.path_unpacked = inpkgdir


def main(hub, args):
    tmpdir = py.path.local.make_numbered_dir("devpi-test", keep=3)
    config = hub.config
    if not config.exists():
        hub.fatal("no api configuration found")
    devindex = DevIndex(tmpdir, config)
    link = devindex.getbestlink(args.pkgspec[0])
    if not link:
        hub.fatal("could not find/receive link")
    devindex.download_and_unpack(link)
    ret = devindex.runtox(link, Popen=hub.Popen, venv=args.venv)
    raise SystemExit(ret)
