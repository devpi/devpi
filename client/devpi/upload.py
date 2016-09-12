import os
import sys
import py
import re

import check_manifest

from devpi_common.metadata import Version, get_pyversion_filetype
from devpi_common.archive import zip_dir
from devpi_common.types import CompareMixin
from .main import HTTPReply, set_devpi_auth_header

def main(hub, args):
    # for now we use distutils/setup.py for register/upload commands.

    # we are going to invoke python setup.py register|sdist|upload
    # but we want to push to our local devpi server,
    # so we need to monkeypatch distutils in the setup.py process

    current = hub.require_valid_current_with_index()
    if not args.index and not current.pypisubmit:
        hub.fatal("no pypisubmit endpoint available for: %s" % current.index)

    if args.path:
        return main_fromfiles(hub, args)

    setup = hub.cwd.join("setup.py")
    if not setup.check():
        hub.fatal("no setup.py found in", hub.cwd)

    setupcfg = read_setupcfg(hub, hub.cwd)
    checkout = Checkout(hub, hub.cwd, hasvcs=setupcfg.get("no-vcs"),
                        setupdir_only=setupcfg.get("setupdir-only"))
    uploadbase = hub.getdir("upload")
    exported = checkout.export(uploadbase)

    exported.prepare()
    archives = []
    if not args.onlydocs:
        archives.extend(exported.setup_build(
                            default_formats=setupcfg.get("formats")))
    if args.onlydocs or args.withdocs:
        p = exported.setup_build_docs()
        if p:
            archives.append(p)
    if not archives:
        hub.fatal("nothing built!")
    name_version = exported.setup_name_and_version()
    uploader = Uploader(hub, args, name_version=name_version)
    if args.index:
        uploader.pypisubmit = hub.current.get_index_url(args.index).url
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
    if args.index:
        uploader.pypisubmit = hub.current.get_index_url(args.index).url
    uploader.do_upload_paths(paths)

class Uploader:
    def __init__(self, hub, args, name_version=None):
        self.hub = hub
        self.args = args
        # allow explicit name and version instead of using pkginfo which
        # has a high failure rate for documentation zips because they miss
        # explicit metadata and the implementation has to guess
        self.name_version = name_version
        self.pypisubmit = hub.current.pypisubmit

    def do_upload_paths(self, paths):
        hub = self.hub
        releasefile2pkginfo = {}
        doczip2pkginfo = {}
        for path in paths:
            for archivepath in get_archive_files(path):
                pkginfo = get_pkginfo(archivepath)
                if pkginfo is None or pkginfo.name is None:
                    hub.error("%s: does not contain PKGINFO, skipping" %
                              archivepath.basename)
                    continue
                if archivepath.basename.endswith(".doc.zip"):
                    doczip2pkginfo[archivepath] = pkginfo
                else:
                    releasefile2pkginfo[archivepath] = pkginfo
                #hub.debug("got pkginfo for %s-%s  %s" %
                #          (pkginfo.name, pkginfo.version, pkginfo.author))
        if self.args.only_latest:
            releasefile2pkginfo = filter_latest(releasefile2pkginfo)
            doczip2pkginfo = filter_latest(doczip2pkginfo)

        for archivepath, pkginfo in releasefile2pkginfo.items():
            self.upload_release_file(archivepath, pkginfo)
        for archivepath, pkginfo in doczip2pkginfo.items():
            self.upload_doc(archivepath, pkginfo)


    def upload_doc(self, path, pkginfo):
        if self.name_version:
            (name, version) = self.name_version
        else:
            (name, version) = (pkginfo.name, pkginfo.version)
        self.post("doc_upload", path,
                {"name": name, "version": version})

    def post(self, action, path, meta):
        hub = self.hub
        assert "name" in meta and "version" in meta, meta
        dic = meta.copy()
        pypi_action = action
        if action == "register":
            pypi_action = "submit"
        dic[":action"] = pypi_action
        dic["protocol_version"] = "1",
        headers = {}
        auth = hub.current.get_auth()
        if not auth:
            hub.fatal("need to be authenticated (use 'devpi login')")
        set_devpi_auth_header(headers, auth)
        if path:
            files = {"content": (path.basename, path.open("rb"))}
        else:
            files = None
        if path:
            msg = "%s of %s to %s" %(action, path.basename, self.pypisubmit)
        else:
            msg = "%s %s-%s to %s" %(action, meta["name"], meta["version"],
                                     self.pypisubmit)
        if self.args.dryrun:
            hub.line("skipped: %s" % msg)
        else:
            r = hub.http.post(self.pypisubmit, dic, files=files,
                              headers=headers,
                              auth=hub.current.get_basic_auth(self.pypisubmit),
                              cert=hub.current.get_client_cert(self.pypisubmit))
            hub._last_http_stati.append(r.status_code)
            r = HTTPReply(r)
            if r.status_code == 200:
                hub.info(msg)
                return True
            else:
                hub.error("%s FAIL %s" %(r.status_code, msg))
                if r.type == "actionlog":
                    for x in r.result:
                        hub.error("  " + x)
                elif r.reason:
                    hub.error(r.reason)
                hub.fatal("POST to %s FAILED" % self.pypisubmit)

    def upload_release_file(self, path, pkginfo):
        meta = {}
        for attr in pkginfo:
            meta[attr] = getattr(pkginfo, attr)
        if self.name_version:
            (meta['name'], meta['version']) = self.name_version
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


# this regexp is taken from pip 8.1.2 (from the vendored packaging)
VERSION_PATTERN = r"""
    v?
    (?:
        (?:(?P<epoch>[0-9]+)!)?                           # epoch
        (?P<release>[0-9]+(?:\.[0-9]+)*)                  # release segment
        (?P<pre>                                          # pre-release
            [-_\.]?
            (?P<pre_l>(a|b|c|rc|alpha|beta|pre|preview))
            [-_\.]?
            (?P<pre_n>[0-9]+)?
        )?
        (?P<post>                                         # post release
            (?:-(?P<post_n1>[0-9]+))
            |
            (?:
                [-_\.]?
                (?P<post_l>post|rev|r)
                [-_\.]?
                (?P<post_n2>[0-9]+)?
            )
        )?
        (?P<dev>                                          # dev release
            [-_\.]?
            (?P<dev_l>dev)
            [-_\.]?
            (?P<dev_n>[0-9]+)?
        )?
    )
    (?:\+(?P<local>[a-z0-9]+(?:[-_\.][a-z0-9]+)*))?       # local version
"""


name_version_regex = re.compile(
    "(.*)-(" + VERSION_PATTERN + ")",
    re.VERBOSE | re.IGNORECASE)


def get_name_version_doczip(basename):
    DOCZIPSUFFIX = ".doc.zip"
    assert basename.endswith(DOCZIPSUFFIX)
    fn = basename[:-len(DOCZIPSUFFIX)]
    name, version = name_version_regex.match(fn).groups()[:2]
    return name, version


class DocZipMeta(CompareMixin):
    def __init__(self, archivepath):
        basename = py.path.local(archivepath).basename
        name, version = get_name_version_doczip(basename)
        self.name = name
        self.version = version
        self.cmpval = (name, version)

    def __repr__(self):
        return "<DocZipMeta name=%r version=%r>" % (self.name, self.version)


def get_pkginfo(archivepath):
    if str(archivepath).endswith(".doc.zip"):
        return DocZipMeta(archivepath)

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
    def __init__(self, hub, setupdir, hasvcs=None, setupdir_only=None):
        self.hub = hub
        assert setupdir.join("setup.py").check(), setupdir
        hasvcs = not hasvcs and not hub.args.novcs
        setupdir_only = bool(setupdir_only or hub.args.setupdironly)
        if hasvcs:
            with setupdir.as_cwd():
                try:
                    hasvcs = check_manifest.detect_vcs().metadata_name
                except check_manifest.Failure:
                    hasvcs = None
                else:
                    if hasvcs not in (".hg", ".git") or setupdir_only:
                        # XXX for e.g. svn we don't do copying
                        self.rootpath = setupdir
                    else:
                        for p in setupdir.parts(reverse=True):
                            if p.join(hasvcs).exists():
                                self.rootpath = p
                                break
                        else:
                            hasvcs = None
        self.hasvcs = hasvcs
        self.setupdir = setupdir
        self.setupdir_only = setupdir_only

    def export(self, basetemp):
        if not self.hasvcs:
            return Exported(self.hub, self.setupdir, self.setupdir)
        with self.rootpath.as_cwd():
            files = check_manifest.get_vcs_files()
        newrepo = basetemp.join(self.rootpath.basename)
        for fn in files:
            source = self.rootpath.join(fn)
            if source.isfile():
                dest = newrepo.join(fn)
                dest.dirpath().ensure(dir=1)
                source.copy(dest, mode=True)
        self.hub.debug("copied", len(files), "files to", newrepo)

        if self.hasvcs not in (".git", ".hg") or self.setupdir_only:
            self.hub.warn("not copying vcs repository metadata for", self.hasvcs)
        else:
            srcrepo = self.rootpath.join(self.hasvcs)
            assert srcrepo.exists(), srcrepo
            destrepo = newrepo.join(self.hasvcs)
            self.rootpath.join(self.hasvcs).copy(destrepo, mode=True)
            self.hub.info("copied repo", srcrepo, "to", destrepo)
        self.hub.debug("%s-exported project to %s -> new CWD" %(
                      self.hasvcs, newrepo))
        setupdir_newrepo = newrepo.join(self.setupdir.relto(self.rootpath))
        return Exported(self.hub, setupdir_newrepo, self.setupdir)

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
        name = self.hub.popen_output(
            [self.python, setup_py, "--name"],
            report=False).splitlines()[-1].strip()
        version = self.hub.popen_output(
            [self.python, setup_py, "--version"],
            report=False).splitlines()[-1].strip()
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
            self.hub.fatal("did not find %s after export of versioned files "
                           "(you may try --no-vcs to prevent the export)" % p)

    def prepare(self):
        self.check_setup()
        if self.target_distdir.check():
            self.hub.line("pre-build: cleaning %s" % self.target_distdir)
            self.target_distdir.remove()
        self.target_distdir.mkdir()

    def setup_build(self, default_formats=None):
        formats = self.hub.args.formats
        if not formats:
            formats = default_formats
            if not formats:
                formats = "sdist.zip" if sys.platform == "win32" else "sdist.tgz"

        formats = [x.strip() for x in formats.split(",")]

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
        out = self.hub.popen_output(
            [self.python, "setup.py", "build_sphinx", "-E",
             "--build-dir", build], cwd=self.rootpath)
        if out is None:
            return
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


def read_setupcfg(hub, path):
    setup_cfg = path.join("setup.cfg")
    if setup_cfg.exists():
        cfg = py.iniconfig.IniConfig(setup_cfg)
        hub.line("detected devpi:upload section in %s" % setup_cfg, bold=True)
        return cfg.sections.get("devpi:upload", {})
    return {}
