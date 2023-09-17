import iniconfig
import os
import sys
import py
import re
import zipfile

import check_manifest
import pep517.meta

from devpi_common.metadata import Version, get_pyversion_filetype
from devpi_common.archive import Archive
from devpi_common.archive import zip_dir
from devpi_common.types import CompareMixin
from .main import HTTPReply, set_devpi_auth_header


def main(hub, args):
    # we use the build module (or setup.py for deprecated formats) for
    # creating releases and upload via direct HTTP requests

    current = hub.require_valid_current_with_index()
    if not args.index and not current.pypisubmit:
        hub.fatal("The current index %s does not support upload."
            "\nMost likely, it is a mirror." % current.index)

    if args.path:
        return main_fromfiles(hub, args)

    setupcfg = read_setupcfg(hub, hub.cwd)
    checkout = Checkout(hub, args, hub.cwd, hasvcs=setupcfg.get("no-vcs"),
                        setupdir_only=setupcfg.get("setupdir-only"))

    with hub.workdir() as uploadbase:
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
        uploader = Uploader(hub, args)
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
    def __init__(self, hub, args):
        self.hub = hub
        self.args = args
        # allow explicit name and version instead of using pkginfo which
        # has a high failure rate for documentation zips because they miss
        # explicit metadata and the implementation has to guess
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
                if isinstance(pkginfo, DocZipMeta):
                    doczip2pkginfo[archivepath] = pkginfo
                else:
                    releasefile2pkginfo[archivepath] = pkginfo
        if self.args.only_latest:
            releasefile2pkginfo = filter_latest(releasefile2pkginfo)
            doczip2pkginfo = filter_latest(doczip2pkginfo)

        for archivepath, pkginfo in releasefile2pkginfo.items():
            self.upload_release_file(archivepath, pkginfo)
        for archivepath, pkginfo in doczip2pkginfo.items():
            self.upload_doc(archivepath, pkginfo)

    def upload_doc(self, path, pkginfo):
        (name, version) = (pkginfo.name, pkginfo.version)
        with self.hub.workdir() as tmp:
            if pkginfo.needs_repackage:
                if version is None:
                    fn = tmp.join('%s.doc.zip' % name)
                else:
                    fn = tmp.join('%s-%s.doc.zip' % (name, version))
                with zipfile.ZipFile(fn.strpath, "w") as z:
                    with Archive(path) as archive:
                        for aname in archive.namelist():
                            z.writestr(aname, archive.read(aname))
                self.hub.info(
                    "repackaged %s to %s" % (path.basename, fn.basename))
                path = fn
            self.post(
                "doc_upload", path,
                {"name": name, "version": version})

    def post(self, action, path, meta):
        hub = self.hub
        assert "name" in meta and "version" in meta, meta
        dic = meta.copy()
        pypi_action = action
        dic[":action"] = pypi_action
        dic["protocol_version"] = "1"
        headers = {}
        auth = hub.current.get_auth()
        if auth:
            auth = (auth[0], hub.derive_token(auth[1], meta['name']))
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
            try:
                r = hub.http.post(self.pypisubmit, dic, files=files,
                                  headers=headers,
                                  auth=hub.current.get_basic_auth(self.pypisubmit),
                                  cert=hub.current.get_client_cert(self.pypisubmit))
            finally:
                if files:
                    for p, f in files.values():
                        f.close()
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
        pyver = get_pyversion_filetype(path.basename)
        meta["pyversion"], meta["filetype"] = pyver
        self.post("file_upload", path, meta=meta)


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


NAME_VERSION_PATTERN = "^(?P<name>.*?)(-(?P<version>" + VERSION_PATTERN + "))?"


doc_archive_regex = re.compile(
    NAME_VERSION_PATTERN + r"\.docs?\.(?P<ext>zip|tar\.gz|tgz)$",
    re.VERBOSE | re.IGNORECASE)


def get_name_version_doczip(basename):
    m = doc_archive_regex.match(basename)
    if m:
        d = m.groupdict()
        needs_repackage = 'zip' not in d['ext']
        return (d['name'], d['version'], needs_repackage)


class DocZipMeta(CompareMixin):
    def __init__(self, name, version, needs_repackage):
        self.name = name
        self.version = version
        self.needs_repackage = needs_repackage
        self.cmpval = (name, version)

    def __repr__(self):
        return "<DocZipMeta name=%r version=%r needs_repackage=%r>" % (
            self.name, self.version, self.needs_repackage)


def get_pkginfo(archivepath):
    info = get_name_version_doczip(archivepath.basename)
    if info is not None:
        return DocZipMeta(*info)

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
    def __init__(self, hub, args, setupdir, hasvcs=None, setupdir_only=None):
        self.hub = hub
        self.args = args
        self.cm_ui = None
        if hasattr(check_manifest, 'UI'):
            self.cm_ui = check_manifest.UI()
        hasvcs = not hasvcs and not args.novcs
        setupdir_only = bool(setupdir_only or args.setupdironly)
        if hasvcs:
            with setupdir.as_cwd():
                try:
                    if self.cm_ui:
                        hasvcs = check_manifest.detect_vcs(self.cm_ui).metadata_name
                    else:
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
            return Exported(self.hub, self.args, self.setupdir, self.setupdir)
        with self.rootpath.as_cwd():
            if self.cm_ui:
                files = check_manifest.get_vcs_files(self.cm_ui)
            else:
                files = check_manifest.get_vcs_files()
        newrepo = basetemp.join(self.rootpath.basename)
        for fn in files:
            source = self.rootpath.join(fn)
            if source.islink():
                dest = newrepo.join(fn)
                dest.dirpath().ensure(dir=1)
                dest.mksymlinkto(source.readlink(), absolute=True)
            elif source.isfile():
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
        return Exported(self.hub, self.args, setupdir_newrepo, self.setupdir)


class Exported:
    def __init__(self, hub, args, rootpath, origrepo):
        self.hub = hub
        self.args = args
        self.rootpath = rootpath
        self.origrepo = origrepo
        self.target_distdir = origrepo.join("dist")

    @property
    def python(self):
        """
        Find the best Python executable for invoking builds and uploads.
        Command line option if used has priority, then a virtualenv if one
        is activated, but otherwise falls back to sys.executable, the Python
        under which devpi client is running.
        """
        python = self.args.python
        if python is None:
            python = self._virtualenv_python()
        if python is None:
            python = sys.executable
        return python

    def _virtualenv_python(self):
        if 'VIRTUAL_ENV' in os.environ:
            return py.path.local.sysfind("python")

    def __str__(self):
        return "<Exported %s>" % self.rootpath

    def setup_name_and_version(self):
        result = pep517.meta.load(self.rootpath.strpath)
        name = result.metadata["name"]
        version = result.metadata["version"]
        self.hub.debug("name, version = %s, %s" % (name, version))
        return name, version

    def prepare(self):
        if self.target_distdir.check():
            self.hub.line("pre-build: cleaning %s" % self.target_distdir)
            self.target_distdir.remove()
        self.target_distdir.mkdir()

    @staticmethod
    def is_default_sdist(format):
        if format == "sdist":
            return True
        parts = format.split(".", 1)
        if len(parts) == 2 and parts[0] == "sdist":
            setup_format = sdistformat(parts[1])
            if sys.platform == "win32":
                return setup_format == "zip"
            else:
                return setup_format == "gztar"
        return False

    def setup_build(self, default_formats=None):
        deprecated_formats = []
        sdist = self.args.sdist
        wheel = self.args.wheel
        formats = self.args.formats
        if formats is None:
            formats = default_formats
        if formats and not sdist and not wheel:
            sdist = None
            wheel = None
            for format in formats.split(","):
                format = format.strip()
                if not format:
                    continue
                if self.is_default_sdist(format):
                    sdist = True
                elif format == "bdist_wheel":
                    wheel = True
                else:
                    deprecated_formats.append(format)
            if sdist and wheel:
                # if both formats are wanted, we do not pass the arguments
                # to python -m build below, so the default behaviour is used
                # see python -m build --help for details
                sdist = False
                wheel = False
            if sdist is None and wheel is None:
                self.hub.warn(
                    "The --formats option is deprecated, "
                    "none of the specified formats '%s' are supported by "
                    "python -m build" % ','.join(sorted(deprecated_formats)))
            elif sdist and not wheel:
                self.hub.warn(
                    "The --formats option is deprecated, "
                    "replace it with --sdist to only get source release "
                    "as with your currently specified format.")
            elif wheel and not sdist:
                self.hub.warn(
                    "The --formats option is deprecated, "
                    "replace it with --wheel to only get wheel release "
                    "as with your currently specified format.")
            else:
                self.hub.warn(
                    "The --formats option is deprecated, "
                    "you can remove it to get the default sdist and wheel "
                    "releases you get with your currently specified formats.")

        cmds = []
        if sdist is not None or wheel is not None:
            cmd = [self.python, "-m", "build"]
            if sdist:
                cmd.append("--sdist")
            if wheel:
                cmd.append("--wheel")
            if self.args.no_isolation:
                cmd.append("--no-isolation")
            cmds.append(cmd)

        for format in sorted(deprecated_formats):
            cmd = [self.python, "setup.py"]
            if format.startswith("sdist."):
                cmd.append("sdist")
                parts = format.split(".", 1)
                if len(parts) == 2:
                    cmd.append("--formats")
                    cmd.append(sdistformat(parts[1]))
                else:
                    self.hub.fatal("Invalid sdist format '%s'.")
            else:
                cmd.append(format)
            self.hub.warn(
                "The '%s' format is invalid for python -m build. "
                "Falling back to '%s' which is deprecated." % (
                    format, ' '.join(cmd[1:])))
            cmds.append(cmd)

        archives = []
        for cmd in cmds:
            distdir = self.rootpath.join("dist")
            if self.rootpath != self.origrepo:
                if distdir.exists():
                    distdir.remove()

            if self.args.verbose:
                ret = self.hub.popen_check(cmd, cwd=self.rootpath)
            else:
                ret = self.hub.popen_output(cmd, cwd=self.rootpath)

            if ret is None:  # dryrun
                continue

            for x in distdir.listdir():  # usually just one
                target = self.target_distdir.join(x.basename)
                x.move(target)
                archives.append(target)
                self.log_build(target)

        return archives

    def setup_build_docs(self):
        name, version = self.setup_name_and_version()
        build = self.rootpath.join("build")
        for guess in ("doc", "docs", "source"):
            docs = self.rootpath.join(guess)
            if docs.isdir():
                if docs.join("conf.py").exists():
                    break
                else:
                    source = docs.join("source")
                    if source.isdir() and source.join("conf.py").exists():
                        build, docs = docs.join("build"), source
                        break
        cmd = ["sphinx-build", "-E", docs, build]
        if self.args.verbose:
            ret = self.hub.popen_check(cmd, cwd=self.rootpath)
        else:
            ret = self.hub.popen_output(cmd, cwd=self.rootpath)
        if ret is None:
            return
        p = self.target_distdir.join("%s-%s.doc.zip" %(name, version))
        zip_dir(build, p)
        self.log_build(p, "[sphinx docs]")
        return p

    def log_build(self, path, suffix=None):
        kb = path.size() / 1000
        if suffix:
            self.hub.line("built: %s %s %skb" % (path, suffix, kb))
        else:
            self.hub.line("built: %s %skb" % (path, kb))


sdistformat2option = {
    "tgz": "gztar",  # gzipped tar-file
    "tar": "tar",    # un-compressed tar
    "zip": "zip",    # compressed zip file
    "tz": "ztar",    # compressed tar file
    "tbz": "bztar",  # bzip2'ed tar-file
}


def sdistformat(format):
    """ return sdist format option. """
    res = sdistformat2option.get(format, None)
    if res is None:
        if res not in sdistformat2option.values():
            raise ValueError("unknown sdist format option: %r" % res)
        res = format
    return res


class SetupCFG:
    notset = object()

    def __init__(self, hub, section):
        self.hub = hub
        self._section = section

    def get(self, key):
        value = self._section.get(key, self.notset)
        if value is not self.notset:
            self.hub.info(
                "Got %s=%r from setup.cfg [devpi:upload]." % (key, value))
            return value
        return None


def read_setupcfg(hub, path):
    setup_cfg = path.join("setup.cfg")
    if setup_cfg.exists():
        cfg = iniconfig.IniConfig(setup_cfg)
        if 'devpi:upload' in cfg.sections:
            hub.line("detected devpi:upload section in %s" % setup_cfg, bold=True)
            return SetupCFG(hub, cfg.sections["devpi:upload"])
    return SetupCFG(hub, {})
