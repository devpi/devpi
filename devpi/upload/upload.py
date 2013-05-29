import os
import re
import sys
import py
from devpi.upload.setuppy import __file__ as fn_setup
from devpi.use import Config
from devpi import log
from devpi.util import version as verlib
from devpi import cached_property
from subprocess import PIPE, STDOUT

fn_setup = fn_setup.rstrip("oc")



def main(hub, args):
    # for now we use distutils/setup.py for register/upload commands.

    # we are going to invoke python setup.py register|sdist|upload
    # but we want to push to our local devpi server,
    # so we need to monkeypatch distutils in the setup.py process

    #newest_version = hub.remoteindex.getnewestversion(

    uploadbase = hub.getdir("upload")
    checkout = Checkout(hub, hub.cwd)
    exported = checkout.export(uploadbase)
    hub.info("hg-exported project to", exported)

    if 0:
        set_new_version(hub, args, exported)
    exported.setup_register()
    exported.setup_upload()

def set_new_version(hub, args, exported):
    if args.setversion:
        newversion = verlib.Version(args.setversion)
        exported.change_versions(newversion)

    pkgname, version = exported.name_and_version()
    link = hub.remoteindex.getbestlink(pkgname)
    if link is None:
        log.info("no remote packages registered yet")
    else:
        indexversion = verlib.Version.frombasename(link.basename)
        if version < indexversion:
            hub.fatal(pkgname, "local", version, "lower than index",
                      indexversion)
        elif version == indexversion:
            if args.setversion:
                hub.fatal("index already has %s-%s" %(pkgname, version))
            newversion = version.autoinc()
            exported.change_versions(newversion)
                #["setup.py", pkgname + os.sep + "__init__.py"])
            n,v = exported.name_and_version()
            assert v == newversion, (str(v), str(newversion))
        else:
            newversion = version
            log.info("good, local", version, "newer than latest remote",
                     indexversion)


def setversion(s, newversion):
    def replaceversion(match):
        vername = match.group(1)
        assign = match.group(2)
        version = match.group(3)
        if not (version[0] == version[-1]):
           return match.group(0)
        version = version[0] + str(newversion) + version[-1]
        return "%s%s%s" %(vername, assign, version)
    news = re.sub(r'''(version|__version__)(\s*=\s*)(['"]\S*['"])''',
                  replaceversion, s)
    return news


def find_parent_subpath(startpath, relpath, raising=True):
    for x in startpath.parts(reversed):
        cand = x.join(relpath)
        if cand.check():
            return cand
    if raising:
        raise ValueError("no subpath %r from %s" %(relpath, startpath))


class Checkout:
    def __init__(self, hub, somepath):
        self.hub = hub
        self.rootpath = find_parent_subpath(somepath, ".hg").dirpath()

    def export(self, basetemp):
        newrepo = basetemp.join(self.rootpath.basename)
        out = self.hub.popen_output("hg st -nmardc", cwd=self.rootpath)
        num = 0
        for fn in out.split("\n"):
            if fn.strip():
                source = self.rootpath.join(fn)
                dest = newrepo.join(fn)
                dest.dirpath().ensure(dir=1)
                source.copy(dest)
                num += 1
        log.debug("copied", num, "files to", newrepo)
        return Exported(self.hub, newrepo, self.rootpath)

class Exported:
    def __init__(self, hub, rootpath, origrepo):
        self.hub = hub
        self.rootpath = rootpath
        self.origrepo = origrepo

    def __str__(self):
        return "<Exported %s>" % self.rootpath

    def detect_versioncandidates(self):
        relpaths = ["setup.py"]
        for x in self.rootpath.listdir():
            init = x.join("__init__.py")
            if init.check():
                relpaths.append(init.relto(self.rootpath))
        return relpaths

    def change_versions(self, newversion, relpaths=None):
        if relpaths is None:
            relpaths = self.detect_versioncandidates()
        for relpath in relpaths:
            cand = self.rootpath.join(relpath)
            if cand.check():
                if self.check_setversion(cand, newversion):
                    cand.copy(self.origrepo.join(relpath))
                    self.hub.info("setversion", relpath, newversion)

    def check_setversion(self, path, newversion):
        log.debug("check_setversion", path)
        content = path.read()
        newcontent = setversion(content, str(newversion))
        if newcontent != content:
            log.debug("changing", path)
            path.write(newcontent)
            return True

    def setup_fullname(self):
        setup_py = self.rootpath.join("setup.py")
        if not setup_py.check():
            self.hub.fatal("no setup.py file")
        fullname = self.hub.popen_output([sys.executable,
                                          setup_py, "--fullname"]).strip()
        self.hub.info("got local pypi-fullname", fullname)
        return fullname

    def name_and_version(self):
        return verlib.guess_pkgname_and_version(self.setup_fullname())

    def setup_register(self):
        hub = self.hub
        pypisubmit = self.hub.config.pypisubmit
        cwd = self.rootpath
        user, password = self.hub.http.auth or ("test", "test")
        hub.debug("registering package at", cwd, "to", pypisubmit)
        out = hub.popen_output([sys.executable, fn_setup, cwd,
             pypisubmit, user, password, "register", "-r", "devpi",],
             cwd = self.rootpath)
        if "Server response (200): OK" in out:
            hub.info("release registered", "%s-%s" % self.name_and_version())
        else:
            hub.fatal("release registration failed\n", out)

    def setup_upload(self):
        config = self.hub.config
        cwd = self.rootpath
        user, password = self.hub.http.auth or ("test", "test")
        out = self.hub.popen_output(
            [sys.executable, fn_setup, cwd, config.pypisubmit,
             user, password,
             "sdist", "upload", "-r", "devpi",],
            cwd=cwd)
        if "Server response (200): OK" in out:
            for line in out.split("\n")[-10:]:
                if line.startswith("Submitting"):
                    self.hub.info(line.replace("Submitting", "submitted"))
                    return
        else:
            self.hub.fatal("could not register releasefile", out)

