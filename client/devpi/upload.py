import os
import py
from devpi import log
from devpi_common.metadata import Version, BasenameMeta, get_pyversion_filetype
from devpi_common.archive import zip_dir
from .main import HTTPReply

def main(hub, args):
    # for now we use distutils/setup.py for register/upload commands.

    # we are going to invoke python setup.py register|sdist|upload
    # but we want to push to our local devpi server,
    # so we need to monkeypatch distutils in the setup.py process

    current = hub.require_valid_current_with_index()
    if not current.pypisubmit:
        hub.fatal("no pypisubmit endpoint available for: %s" % current.index)

    if args.path:
        return main_fromfiles(hub, args)

    setup = hub.cwd.join("setup.py")
    if not setup.check():
        hub.fatal("no setup.py found in", hub.cwd)
    checkout = Checkout(hub, hub.cwd)
    uploadbase = hub.getdir("upload")
    exported = checkout.export(uploadbase)

    exported.prepare()
    archives = []
    if not args.onlydocs:
        archives.extend(exported.setup_build())
    if args.onlydocs or args.withdocs:
        archives.append(exported.setup_build_docs())
    if not archives:
        hub.fatal("nothing built!")
    uploader = Uploader(hub, args)
    uploader.do_upload_paths(archives)

def filter_latest(path_pkginfo):
    name_version_path = {}
    for archivepath, pkginfo in path_pkginfo.items():
        name = pkginfo.name
        iversion = Version(pkginfo.version)
        data = name_version_path.get(name)
        if data is None or data[0] < iversion:
            name_version_path[name] = (iversion, pkginfo, archivepath)
    retval = {}
    for x in name_version_path.values():
        retval[x[2]] = x[1]
    return retval

def main_fromfiles(hub, args):
    paths = []
    for p in args.path:
        p = py.path.local(os.path.expanduser(p))
        if not p.check():
            hub.fatal("path does not exist: %s" % p)
        if p.isdir() and not args.fromdir:
            hub.fatal("%s: is a directory but --from-dir not specified" % p)
        paths.append(p)

    uploader = Uploader(hub, args)
    uploader.do_upload_paths(paths)

class Uploader:
    def __init__(self, hub, args):
        self.hub = hub
        self.args = args

    def do_upload_paths(self, paths):
        hub = self.hub
        path2pkginfo = {}
        for path in paths:
            for archivepath in get_archive_files(path):
                pkginfo = get_pkginfo(archivepath)
                if pkginfo is None or pkginfo.name is None:
                    hub.error("%s: does not contain PKGINFO, skipping" %
                              archivepath.basename)
                    continue
                path2pkginfo[archivepath] = pkginfo
                #hub.debug("got pkginfo for %s-%s  %s" %
                #          (pkginfo.name, pkginfo.version, pkginfo.author))
        if self.args.only_latest:
            path2pkginfo = filter_latest(path2pkginfo)
        for archivepath, pkginfo in path2pkginfo.items():
            if str(archivepath).endswith(".doc.zip"):
                self.upload_doc(archivepath, pkginfo)
            else:
                self.upload_release_file(archivepath, pkginfo)

    def upload_doc(self, path, pkginfo):
        self.post("doc_upload", path,
                {"name": pkginfo.name, "version": pkginfo.version})

    def post(self, action, path, meta):
        hub = self.hub
        assert "name" in meta and "version" in meta, meta
        dic = meta.copy()
        pypi_action = action
        if action == "register":
            pypi_action = "submit"
        dic[":action"] = pypi_action
        dic["protocol_version"] = "1",
        auth = hub.current.get_auth()
        if not auth:
            hub.fatal("need to be authenticated (use 'devpi login')")
        if path:
            files = {"content": (path.basename, path.open("rb"))}
        else:
            files = None
        if path:
            msg = "%s of %s to %s" %(action, path.basename, hub.current.index)
        else:
            msg = "%s %s-%s to %s" %(action, meta["name"], meta["version"],
                                     hub.current.index)
        if self.args.dryrun:
            hub.line("skipped: %s" % msg)
        else:
            r = hub.http.post(hub.current.index, dic, files=files, auth=auth)
            r = HTTPReply(r)
            if r.status_code == 200:
                hub.info(msg)
                return True
            else:
                hub.error("%s FAIL %s" %(r.status_code, msg))
                if r.type == "actionlog":
                    for x in r.result:
                        hub.error("  " + x)

    def upload_release_file(self, path, pkginfo):
        meta = {}
        for attr in pkginfo:
            meta[attr] = getattr(pkginfo, attr)
        self.post("register", None, meta=meta)
        pyver = get_pyversion_filetype(path.basename)
        meta["pyversion"], meta["filetype"] = pyver
        self.post("file_upload", path, meta=meta)

# taken from devpi-server/extpypi.py
ALLOWED_ARCHIVE_EXTS = ".egg .whl .tar.gz .tar.bz2 .tar .tgz .zip".split()
def get_archive_files(path):
    if path.isfile():
        yield path
        return
    for x in path.visit():
        if not x.check(file=1):
            continue
        for name in ALLOWED_ARCHIVE_EXTS:
            if x.basename.endswith(name):
                yield x

def get_pkginfo(archivepath):
    if str(archivepath).endswith(".doc.zip"):
        return BasenameMeta(archivepath)

    if archivepath.ext == ".whl":
        # workaround for https://bugs.launchpad.net/pkginfo/+bug/1227788
        import twine.wheel
        wheel = twine.wheel.Wheel(str(archivepath))
        wheel.parse(wheel.read())
        return wheel

    import pkginfo
    info = pkginfo.get_metadata(str(archivepath))
    return info


def find_parent_subpath(startpath, relpath, raising=True):
    for x in startpath.parts(reversed):
        cand = x.join(relpath)
        if cand.check():
            return cand
    if raising:
        raise ValueError("no subpath %r from %s" %(relpath, startpath))


class Checkout:
    def __init__(self, hub, setupdir):
        self.hub = hub
        self.rootpath = setupdir
        assert setupdir.join("setup.py").check(), setupdir
        hasvcs = not hub.args.novcs
        if hasvcs:
            hasvcs = False
            if find_parent_subpath(self.rootpath, ".hg", raising=False):
                if py.path.local.sysfind("hg"):
                    hasvcs = "hg"
            elif find_parent_subpath(self.rootpath, ".git", raising=False):
                if py.path.local.sysfind("git"):
                    hasvcs = "git"
        self.hasvcs = hasvcs

    def export(self, basetemp):
        if not self.hasvcs:
            return Exported(self.hub, self.rootpath, self.rootpath)
        newrepo = basetemp.join(self.rootpath.basename)
        if self.hasvcs == "hg":
            out = self.hub.popen_output("hg st -nmac .", cwd=self.rootpath)
        elif self.hasvcs == "git":
            out = self.hub.popen_output("git ls-files .", cwd=self.rootpath)
        num = 0
        for fn in out.split("\n"):
            if fn.strip():
                source = self.rootpath.join(fn)
                dest = newrepo.join(fn)
                dest.dirpath().ensure(dir=1)
                source.copy(dest)
                num += 1
        log.debug("copied %s files to %s", num, newrepo)
        self.hub.info("%s-exported project to %s -> new CWD" %(
                      self.hasvcs, newrepo))
        return Exported(self.hub, newrepo, self.rootpath)

class Exported:
    def __init__(self, hub, rootpath, origrepo):
        self.hub = hub
        self.rootpath = rootpath
        self.origrepo = origrepo
        self.target_distdir = origrepo.join("dist")
        python = py.path.local.sysfind("python")
        if not python:
            raise ValueError("could not find 'python' executable")
        self.python = str(python)

    def __str__(self):
        return "<Exported %s>" % self.rootpath

    def setup_name_and_version(self):
        setup_py = self.rootpath.join("setup.py")
        if not setup_py.check():
            self.hub.fatal("no setup.py file")
        name = self.hub.popen_output([self.python, setup_py, "--name"],
                                     report=False).strip()
        version = self.hub.popen_output(
            [self.python, setup_py, "--version"], report=False).strip()
        self.hub.debug("name, version = %s, %s" %(name, version))
        return name, version

    def _getuserpassword(self):
        auth = self.hub.current.get_auth()
        if auth:
            return auth
        return "_test", "test"

    def check_setup(self):
        p = self.rootpath.join("setup.py")
        if not p.check():
            self.hub.fatal("did not find %s after "
                           "export of versioned files" % p)

    def prepare(self):
        self.check_setup()
        if self.target_distdir.check():
            self.hub.line("pre-build: cleaning %s" % self.target_distdir)
            self.target_distdir.remove()
        self.target_distdir.mkdir()

    def setup_build(self):
        formats = [x.strip() for x in self.hub.args.formats.split(",")]

        archives = []
        for format in formats:
            if not format:
                continue
            buildcommand = []
            if format == "sdist" or format.startswith("sdist."):
                buildcommand = ["sdist"]
                parts = format.split(".", 1)
                if len(parts) > 1:
                    setup_format = sdistformat(parts[1])
                    buildcommand.extend(["--formats", setup_format])
            else:
                buildcommand.append(format)
            pre = [self.python, "setup.py"]
            cmd = pre + buildcommand

            distdir = self.rootpath.join("dist")
            if self.rootpath != self.origrepo:
                if distdir.exists():
                    distdir.remove()
            out = self.hub.popen_output(cmd, cwd=self.rootpath)
            if out is None:  # dryrun
                continue
            for x in distdir.listdir():  # usually just one
                target = self.target_distdir.join(x.basename)
                x.move(target)
                archives.append(target)
                self.log_build(target, "[%s]" %format.upper())
        return archives

    def setup_build_docs(self):
        name, version = self.setup_name_and_version()
        cwd = self.rootpath
        build = cwd.join("build")
        self.hub.popen_output(
            [self.python, "setup.py", "build_sphinx", "-E",
             "--build-dir", build])
        p = self.target_distdir.join("%s-%s.doc.zip" %(name, version))
        html = build.join("html")
        zip_dir(html, p)
        self.log_build(p, "[sphinx docs]")
        return p

    def log_build(self, path, suffix):
        kb = path.size() / 1000
        self.hub.line("built: %s %s %skb" %(path, suffix, kb))


sdistformat2option = {
    "tgz": "gztar",  # gzipped tar-file
    "tar": "tar",    # un-compressed tar
    "zip": "zip",    # comparessed zip file
    "tz": "ztar",    # compressed tar file
    "tbz": "bztar",  # bzip2'ed tar-file
}

#def getallformats():
#    return set(sdistformat2option) + set(sdistformat2option.values())

def sdistformat(format):
    """ return sdist format option. """
    res = sdistformat2option.get(format, None)
    if res is None:
        if res not in sdistformat2option.values():
            raise ValueError("unknown sdist format option: %r" % res)
        res = format
    return res

