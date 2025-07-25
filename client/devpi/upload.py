import iniconfig
import os
import sys
import re
import shutil
import zipfile

import build.util
import check_manifest

from contextlib import suppress
from devpi_common.metadata import Version, get_pyversion_filetype
from devpi_common.metadata import splitext_archive
from devpi_common.archive import Archive
from devpi_common.archive import zip_dir
from devpi_common.contextlib import chdir
from devpi_common.types import CompareMixin
from .main import HTTPReply, set_devpi_auth_header
from pathlib import Path
from subprocess import CalledProcessError
from traceback import format_exception_only
try:
    import tomllib
except ImportError:
    import tomli as tomllib


def main(hub, args):
    # we use the build module (or setup.py for deprecated formats) for
    # creating releases and upload via direct HTTP requests

    current = hub.require_valid_current_with_index()
    if not args.index and not current.pypisubmit:
        hub.fatal(
            "The current index %s does not support upload."
            "\nMost likely, it is a mirror." % current.index)

    if args.path:
        return main_fromfiles(hub, args)

    cfg = read_config(hub, hub.cwd)
    checkout = Checkout(hub, args, hub.cwd, hasvcs=cfg.no_vcs,
                        setupdir_only=cfg.setupdir_only)

    with hub.workdir() as uploadbase:
        exported = checkout.export(uploadbase)

        exported.prepare()
        archives = []
        if not args.onlydocs:
            archives.extend(exported.setup_build(cfg=cfg))
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
        p = Path(p).expanduser()
        if not p.exists():
            hub.fatal("path does not exist: %s" % p)
        if p.is_dir() and not args.fromdir:
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
                              archivepath.name)
                    continue
                if isinstance(pkginfo, DocZipMeta):
                    doczip2pkginfo[archivepath] = pkginfo
                else:
                    releasefile2pkginfo[archivepath] = pkginfo
        if self.args.only_latest:
            releasefile2pkginfo = filter_latest(releasefile2pkginfo)
            doczip2pkginfo = filter_latest(doczip2pkginfo)

        for archivepath, pkginfo in sorted(releasefile2pkginfo.items()):
            self.upload_release_file(archivepath, pkginfo)
        for archivepath, pkginfo in doczip2pkginfo.items():
            self.upload_doc(archivepath, pkginfo)

    def upload_doc(self, path, pkginfo):
        (name, version) = (pkginfo.name, pkginfo.version)
        with self.hub.workdir() as tmp:
            if pkginfo.needs_repackage:
                if version is None:
                    fn = tmp / f'{name}.doc.zip'
                else:
                    fn = tmp / f'{name}-{version}.doc.zip'
                with zipfile.ZipFile(str(fn), "w") as z:
                    with Archive(path) as archive:
                        for aname in archive.namelist():
                            z.writestr(aname, archive.read(aname))
                self.hub.info(
                    "repackaged %s to %s" % (path.name, fn.name))
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
            msg = f"{action} of {path.name} to {self.pypisubmit}"
        else:
            msg = "%s %s-%s to %s" %(action, meta["name"], meta["version"],
                                     self.pypisubmit)
        if self.args.dryrun:
            hub.line("skipped: %s" % msg)
        else:
            files = {"content": (path.name, path.open("rb"))} if path else None
            try:
                r = hub.http.post(self.pypisubmit, dic, files=files,
                                  headers=headers,
                                  auth=hub.current.get_basic_auth(self.pypisubmit),
                                  cert=hub.current.get_client_cert(self.pypisubmit))
            finally:
                if files:
                    for _p, f in files.values():
                        f.close()
            hub._last_http_stati.append(r.status_code)
            r = HTTPReply(r)
            if r.status_code == 200:
                hub.info(msg)
                return
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
        pyver = get_pyversion_filetype(path.name)
        meta["pyversion"], meta["filetype"] = pyver
        self.post("file_upload", path, meta=meta)


ALLOWED_ARCHIVE_EXTS = [
    ".egg",
    ".tar",
    ".tar.bz2",
    ".tar.gz",
    ".tgz",
    ".whl",
    ".zip",
]


def get_archive_files(path):
    if path.is_file():
        yield path
        return
    for x in path.rglob("*"):
        if not x.is_file():
            continue
        for name in ALLOWED_ARCHIVE_EXTS:
            if x.name.endswith(name):
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
    return None


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
    info = get_name_version_doczip(archivepath.name)
    if info is not None:
        return DocZipMeta(*info)

    import pkginfo
    (name, ext) = splitext_archive(str(archivepath))
    ext = ext.lower()
    if ext == '.whl':
        cls = pkginfo.Wheel
    elif ext == '.egg':
        cls = pkginfo.BDist
    else:
        cls = pkginfo.SDist
    result = cls(str(archivepath))
    if result.name is None and result.metadata_version and sys.version_info < (3, 8):
        # add rudimentary support for new metadata, as only newer
        # versions of pkginfo not available for Python 3.7 support it
        # and added automatic fallbacks
        header_attrs = pkginfo.distribution.HEADER_ATTRS
        newest_headers = header_attrs[max(header_attrs)]
        header_attrs.setdefault(result.metadata_version, newest_headers)
        result.extractMetadata()
    return result


def find_parent_subpath(startpath, relpath, *, raising=True):
    for x in startpath.parts(reversed):
        cand = x.join(relpath)
        if cand.check():
            return cand
    if raising:
        raise ValueError("no subpath %r from %s" % (relpath, startpath))
    return None


class Checkout:
    def __init__(self, hub, args, setupdir, hasvcs=None, setupdir_only=None):
        setupdir = Path(setupdir)
        self.hub = hub
        self.args = args
        self.cm_ui = None
        if hasattr(check_manifest, 'UI'):
            self.cm_ui = check_manifest.UI()
        hasvcs = not hasvcs and not args.novcs
        setupdir_only = bool(setupdir_only or args.setupdironly)
        if hasvcs:
            with chdir(setupdir):
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
                        self.rootpath = Path(setupdir)
                    else:
                        for p in (setupdir, *setupdir.parents):
                            if p.joinpath(hasvcs).exists():
                                self.rootpath = p
                                break
                        else:
                            hasvcs = None
        self.hasvcs = hasvcs
        self.setupdir = setupdir
        self.setupdir_only = setupdir_only

    def export(self, basetemp):
        assert isinstance(basetemp, Path)
        if not self.hasvcs:
            return Exported(self.hub, self.args, self.setupdir, self.setupdir)
        with chdir(self.rootpath):
            if self.cm_ui:
                files = check_manifest.get_vcs_files(self.cm_ui)
            else:
                files = check_manifest.get_vcs_files()
        newrepo = basetemp / self.rootpath.name
        for fn in files:
            source = self.rootpath / fn
            dest = newrepo / fn
            if source.is_dir() and not source.is_symlink():
                dest.mkdir(parents=True, exist_ok=True)
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, dest, follow_symlinks=False)
        self.hub.debug("copied", len(files), "files to", newrepo)

        if self.hasvcs not in (".git", ".hg") or self.setupdir_only:
            self.hub.warn("not copying vcs repository metadata for", self.hasvcs)
        else:
            srcrepo = self.rootpath / self.hasvcs
            assert srcrepo.exists(), srcrepo
            destrepo = newrepo / self.hasvcs
            source = self.rootpath / self.hasvcs
            shutil.copytree(srcrepo, destrepo)
            self.hub.info("copied repo", srcrepo, "to", destrepo)
        self.hub.debug(
            "%s-exported project to %s -> new CWD" % (self.hasvcs, newrepo))
        setupdir_newrepo = newrepo / self.setupdir.relative_to(self.rootpath)
        return Exported(self.hub, self.args, setupdir_newrepo, self.setupdir)


class Exported:
    def __init__(self, hub, args, rootpath, origrepo):
        self.hub = hub
        self.args = args
        self.rootpath = rootpath
        self.origrepo = origrepo
        self.target_distdir = origrepo / "dist"

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
        return shutil.which("python") if 'VIRTUAL_ENV' in os.environ else None

    def __str__(self):
        return "<Exported %s>" % self.rootpath

    def setup_name_and_version(self):
        try:
            metadata = build.util.project_wheel_metadata(
                str(self.rootpath), isolated=not self.args.no_isolation)
        except build.BuildBackendException as e:
            exc = '\n'.join(format_exception_only(
                e.__class__, e))
            if isinstance(e.exception, CalledProcessError):
                process_exc = '\n'.join(format_exception_only(
                    e.exception.__class__, e.exception))
                self.hub.fatal(
                    "%s%s%s" % (exc, process_exc, e.exception.stdout.decode()))
            self.hub.fatal(exc)
        name = metadata["name"]
        version = metadata["version"]
        self.hub.debug("name, version = %s, %s" % (name, version))
        return name, version

    def prepare(self):
        self.hub.line("pre-build: cleaning %s" % self.target_distdir)
        if self.target_distdir.exists():
            shutil.rmtree(self.target_distdir)
        self.target_distdir.mkdir()

    @staticmethod
    def is_default_sdist(sdist_format):
        if sdist_format == "sdist":
            return True
        parts = sdist_format.split(".", 1)
        if len(parts) == 2 and parts[0] == "sdist":
            option = sdistformat(parts[1])
            return option == "zip" if sys.platform == "win32" else option == "gztar"
        return False

    def setup_build(self, cfg=None):
        deprecated_formats = []
        sdist = cfg.sdist or self.args.sdist
        wheel = cfg.wheel or self.args.wheel
        formats = self.args.formats
        if formats is not None:
            formats = formats.split(",")
        if formats is None and cfg is not None:
            formats = cfg.formats
        if formats and not sdist and not wheel:
            sdist = None
            wheel = None
            for sdist_format in (x.strip() for x in formats):
                if not sdist_format:
                    continue
                if self.is_default_sdist(sdist_format):
                    sdist = True
                elif sdist_format == "bdist_wheel":
                    wheel = True
                else:
                    deprecated_formats.append(sdist_format)
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

        for sdist_format in sorted(deprecated_formats):
            cmd = [self.python, "setup.py"]
            if sdist_format.startswith("sdist."):
                cmd.append("sdist")
                parts = sdist_format.split(".", 1)
                if len(parts) == 2:
                    cmd.append("--formats")
                    cmd.append(sdistformat(parts[1]))
                else:
                    self.hub.fatal("Invalid sdist format '%s'.")
            else:
                cmd.append(sdist_format)
            self.hub.warn(
                "The '%s' format is invalid for python -m build. "
                "Falling back to '%s' which is deprecated." % (
                    sdist_format, ' '.join(cmd[1:])))
            cmds.append(cmd)

        archives = []
        for cmd in cmds:
            distdir = self.rootpath / "dist"
            if self.rootpath != self.origrepo and distdir.exists():
                shutil.rmtree(distdir)

            if self.args.verbose:
                ret = self.hub.popen_check(cmd, cwd=self.rootpath)
            else:
                ret = self.hub.popen_output(cmd, cwd=self.rootpath)

            if ret is None:  # dryrun
                continue

            for x in sorted(distdir.iterdir()):  # usually just one
                target = self.target_distdir / x.name
                shutil.move(x, target)
                archives.append(target)
                self.log_build(target)

        return archives

    def setup_build_docs(self):
        name, version = self.setup_name_and_version()
        build = self.rootpath / "build"
        if build.exists():
            shutil.rmtree(build)
        for guess in ("doc", "docs", "source"):
            docs = self.rootpath / guess
            if docs.is_dir():
                if docs.joinpath("conf.py").is_file():
                    break
                source = docs / "source"
                if source.is_dir() and source.joinpath("conf.py").is_file():
                    build = docs / "build"
                    docs = source
                    break
        cmd = ["sphinx-build", "-E", docs, build]
        if self.args.verbose:
            ret = self.hub.popen_check(cmd, cwd=self.rootpath)
        else:
            ret = self.hub.popen_output(cmd, cwd=self.rootpath)
        if ret is None:
            return None
        p = self.target_distdir / f"{name}-{version}.doc.zip"
        zip_dir(build, p)
        self.log_build(p, "[sphinx docs]")
        return p

    def log_build(self, path, suffix=None):
        kb = path.stat().st_size // 1000
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


def sdistformat(sdist_format):
    """ return sdist format option. """
    res = sdistformat2option.get(sdist_format)
    if res is None:
        if res not in sdistformat2option.values():
            raise ValueError("unknown sdist format option: %r" % res)
        res = sdist_format
    return res


def strtobool(val):
    val = val.lower()
    if val in ('y', 'yes', 't', 'true', 'on', '1'):
        return True
    elif val in ('n', 'no', 'f', 'false', 'off', '0'):
        return False
    else:
        raise ValueError(f"Invalid truth value {val!r}, use 'y', 'yes', 't', 'true', 'on', '1' for True, or 'n', 'no', 'f', 'false', 'off', '0' for False.")


class NullCFG:
    formats = None
    no_vcs = None
    sdist = None
    setupdir_only = None
    wheel = None


class PyProjectTOML:
    notset = object()

    def __init__(self, hub, section):
        self.hub = hub
        self._section = section

    def _get(self, key):
        value = self._section.get(key, self.notset)
        if value is not self.notset:
            self.hub.info(
                f"Got {key}={value!r} from pyproject.toml [tool.devpi.upload].")
            self._validbool(key, value)
            return value
        return None

    def _validbool(self, key, value):
        if value is None:
            return
        if not isinstance(value, bool):
            self.hub.fatal(
                f"Got non-boolean {value!r} for {key!r}, use true or false.")

    @property
    def formats(self):
        formats = self._section.get("formats")
        if formats is None:
            return None
        self.hub.fatal(
            "The 'formats' option is deprecated and not supported in pyproject.toml.")

    @property
    def no_vcs(self):
        return self._get("no-vcs")

    @property
    def sdist(self):
        return self._get("sdist")

    @property
    def setupdir_only(self):
        return self._get("setupdir-only")

    @property
    def wheel(self):
        return self._get("wheel")


class SetupCFG:
    notset = object()

    def __init__(self, hub, section):
        self.hub = hub
        self._section = section

    def _get(self, key):
        value = self._section.get(key, self.notset)
        if value is not self.notset:
            self.hub.info(
                "Got %s=%r from setup.cfg [devpi:upload]." % (key, value))
            return value
        return None

    def _validbool(self, value):
        actual = bool(value)
        expected = False
        with suppress(ValueError):
            expected = strtobool(value)
        if actual != expected:
            self.hub.warning(
                f"Got {value!r} from config, which is interpreted as True. "
                f"If you meant 'False', "
                f"use an empty value or remove the line completely.")

    @property
    def formats(self):
        formats = self._get("formats")
        if formats is None:
            return None
        return formats.split(",")

    @property
    def no_vcs(self):
        no_vcs = self._get("no-vcs")
        if no_vcs is None:
            return None
        self._validbool(no_vcs)
        return bool(no_vcs)

    @property
    def sdist(self):
        sdist = self._get("sdist")
        if sdist is None:
            return None
        try:
            return strtobool(sdist)
        except ValueError as e:
            self.hub.fatal(f"{e}")

    @property
    def setupdir_only(self):
        setupdir_only = self._get("setupdir-only")
        if setupdir_only is None:
            return None
        self._validbool(setupdir_only)
        return bool(setupdir_only)

    @property
    def wheel(self):
        wheel = self._get("wheel")
        if wheel is None:
            return None
        try:
            return strtobool(wheel)
        except ValueError as e:
            self.hub.fatal(f"{e}")


def read_pyprojecttoml(hub, path):
    pyproject_toml = Path(path) / "pyproject.toml"
    if pyproject_toml.is_file():
        try:
            with pyproject_toml.open("rb") as f:
                cfg = tomllib.load(f)
        except tomllib.TOMLDecodeError as e:
            hub.fatal(f"Error loading {pyproject_toml}:\n{e}")
        section = cfg.get('tool', {}).get('devpi', {}).get('upload')
        if section is not None:
            hub.line(
                f"detected tool.devpi.upload section in {pyproject_toml}",
                bold=True)
            return PyProjectTOML(hub, section)
    return None


def read_setupcfg(hub, path):
    setup_cfg = Path(path) / "setup.cfg"
    if setup_cfg.is_file():
        cfg = iniconfig.IniConfig(setup_cfg)
        if 'devpi:upload' in cfg.sections:
            hub.line("detected devpi:upload section in %s" % setup_cfg, bold=True)
            return SetupCFG(hub, cfg.sections["devpi:upload"])
    return None


def read_config(hub, path):
    setupcfg = read_setupcfg(hub, path)
    pyprojecttoml = read_pyprojecttoml(hub, path)
    if pyprojecttoml and setupcfg:
        hub.fatal("Got configuration in pyproject.toml and setup.cfg, choose one.")
    if pyprojecttoml is not None:
        return pyprojecttoml
    if setupcfg is not None:
        return setupcfg
    return NullCFG()
