from __future__ import annotations

from .types import CompareMixin
from .validation import normalize_name
from packaging.requirements import Requirement as BaseRequirement
from packaging_legacy.version import parse as parse_version
from typing import TYPE_CHECKING
import posixpath
import re


if TYPE_CHECKING:
    from packaging_legacy.version import LegacyVersion
    from packaging_legacy.version import Version as PackagingVersion


ALLOWED_ARCHIVE_EXTS = {
    ".deb",
    ".dmg",
    ".doc.zip",
    ".egg",
    ".exe",
    ".msi",
    ".rpm",
    ".tar",
    ".tar.bz2",
    ".tar.gz",
    ".tgz",
    ".whl",
    ".zip",
}


_releasefile_suffix_rx = re.compile(
    r"(\.deb|\.dmg|\.msi|\.zip|\.tar\.gz|\.tgz|\.tar\.bz2|"
    r"\.doc\.zip|"
    r"\.macosx-\d+.*|"
    r"\.linux-.*|"
    r"\-[^-]+?\.src\.rpm|"
    r"\-[^-]+?\.rpm|"
    r"\.win-amd68-py[23]\.\d\..*|"
    r"\.win32-py[23]\.\d\..*|"
    r"\.win.*\..*|"
    r"-(?:py|cp|ip|pp|jy)[23][\d\.]*.*\..*|"
    r")$", re.IGNORECASE)

# see also PEP425 for supported "python tags"
_pyversion_type_rex = re.compile(
    r"(py|cp|ip|pp|jy)([\d\.py]+).*\.(exe|egg|msi|whl)", re.IGNORECASE)
_ext2type = dict(exe="bdist_wininst", egg="bdist_egg", msi="bdist_msi",
                 whl="bdist_wheel")

_wheel_file_re = re.compile(
    r"""^(?P<namever>(?P<name>.+?)-(?P<ver>.*?))
    ((-(?P<build>\d.*?))?-(?P<pyver>.+?)-(?P<abi>.+?)-(?P<plat>.+?)
    \.whl|\.dist-info)$""",
    re.VERBOSE)

_pep404_nameversion_re = re.compile(
    r"^(?P<name>[^.]+?)-(?P<ver>"
    r"(?:[1-9]\d*!)?"              # [N!]
    r"(?:0|[1-9]\d*)"             # N
    r"(?:\.(?:0|[1-9]\d*))*"        # (.N)*
    r"(?:(?:a|b|rc)(?:0|[1-9]\d*))?"  # [{a|b|rc}N]
    r"(?:\.post(?:0|[1-9]\d*))?"    # [.postN]
    r"(?:\.dev(?:0|[1-9]\d*))?"     # [.devN]
    r"(?:\+(?:[a-z0-9]+(?:[-_\.][a-z0-9]+)*))?"  # local version
    r")$")

_legacy_nameversion_re = re.compile(
    r"^(?P<name>[^.]+?)-(?P<ver>"
    r"(?:[1-9]\d*!)?"              # [N!]
    r"(?:0|[1-9]\d*)"             # N
    r"(?:\.(?:0|[1-9]\d*))*"        # (.N)*
    r"(?:(?:a|b|rc|alpha|beta)(?:0|[1-9]\d*))?"  # [{a|b|rc}N]
    r"(?:\.post(?:0|[1-9]\d*))?"    # [.postN]
    r"(?:\.dev(?:0|[1-9]\d*))?"     # [.devN]
    r"(?:\-(?:[a-z0-9]+(?:[-_\.][a-z0-9]+)*))?"  # local version
    r")$")


def get_pyversion_filetype(basename):
    _, _, suffix = splitbasename(basename)
    if suffix in (".zip", ".tar.gz", ".tgz", "tar.bz2"):
        return ("source", "sdist")
    m = _pyversion_type_rex.search(suffix)
    if not m:
        return ("any", "bdist_dumb")
    (tag, pyversion, ext) = m.groups()
    if pyversion == "2.py3":  # "universal" wheel with no C
        # arbitrary but pypi/devpi makes no special use
        # of "pyversion" anyway?!
        pyversion = "2.7"
    elif "." not in pyversion:
        if tag in ("cp", "pp") and pyversion.startswith("3"):
            pyversion = ".".join((pyversion[0], pyversion[1:]))
        else:
            pyversion = ".".join(pyversion)
    return (pyversion, _ext2type[ext])


def splitbasename(path, checkarch=True):
    nameversion, ext = splitext_archive(path)
    if ext == '.whl':
        m = _wheel_file_re.match(path)
        if m:
            info = m.groupdict()
            return (
                info['name'],
                info['ver'],
                '-%s-%s-%s.whl' % (info['pyver'], info['abi'], info['plat']))
    if checkarch and ext.lower() not in ALLOWED_ARCHIVE_EXTS:
        raise ValueError("invalid archive type %r in: %s" % (ext, path))
    m = _releasefile_suffix_rx.search(path)
    if m:
        ext = m.group(1)
    if len(ext):
        nameversion = path[:-len(ext)]
    else:
        nameversion = path
    if '-' not in nameversion:  # no version
        return nameversion, "", ext
    m = _pep404_nameversion_re.match(nameversion)
    if m:
        (projectname, version) = m.groups()
        return projectname, version, ext
    m = _legacy_nameversion_re.match(nameversion)
    if m:
        (projectname, version) = m.groups()
        return projectname, version, ext
    (projectname, version) = nameversion.rsplit('-', 1)
    return projectname, version, ext


DOCZIPSUFFIX = ".doc.zip"


def splitext_archive(basename):
    basename = getattr(basename, "basename", basename)
    if basename.lower().endswith(DOCZIPSUFFIX):
        ext = basename[-len(DOCZIPSUFFIX):]
        base = basename[:-len(DOCZIPSUFFIX)]
    else:
        base, ext = posixpath.splitext(basename)
        if base.lower().endswith('.tar'):
            ext = base[-4:] + ext
            base = base[:-4]
    return base, ext


class Version(str):
    __slots__ = ('_cmpstr', '_cmpval')
    _cmpstr: str
    _cmpval: LegacyVersion | PackagingVersion

    def __eq__(self, other):
        if not isinstance(other, Version):
            raise NotImplementedError
        return self.cmpval == other.cmpval

    def __ge__(self, other):
        if not isinstance(other, Version):
            raise NotImplementedError
        return self.cmpval >= other.cmpval

    def __gt__(self, other):
        if not isinstance(other, Version):
            raise NotImplementedError
        return self.cmpval > other.cmpval

    def __le__(self, other):
        if not isinstance(other, Version):
            raise NotImplementedError
        return self.cmpval <= other.cmpval

    def __lt__(self, other):
        if not isinstance(other, Version):
            raise NotImplementedError
        return self.cmpval < other.cmpval

    def __ne__(self, other):
        if not isinstance(other, Version):
            raise NotImplementedError
        return self.cmpval != other.cmpval

    def __repr__(self):
        orig = super().__repr__()
        return f"{self.__class__.__name__}({orig})"

    @property
    def cmpval(self):
        _cmpval = getattr(self, '_cmpval', None)
        if _cmpval is None:
            self._cmpval = _cmpval = parse_version(self)
        return _cmpval

    def is_prerelease(self):
        return self.cmpval.is_prerelease

    @property
    def string(self):
        return str(self)


class BasenameMeta(CompareMixin):
    def __init__(self, obj, sameproject=False):
        self.obj = obj
        # none of the below should be done lazily, as devpi_server.mirror
        # essentially uses this to validate parsed links
        basename = getattr(obj, "basename", obj)
        if not isinstance(basename, str):
            raise ValueError("need object with basename attribute")
        assert "/" not in basename, (obj, basename)
        name, version, ext = splitbasename(basename, checkarch=False)
        self.name = name
        self.version = version
        self.ext = ext
        if sameproject:
            self.cmpval = (parse_version(version), normalize_name(name), ext)
        else:
            self.cmpval = (normalize_name(name), parse_version(version), ext)

    def __repr__(self):
        return "<BasenameMeta name=%r version=%r>" % (self.name, self.version)


def get_latest_version(seq, stable=False):
    versions = [Version(x) for x in seq]
    if stable:
        versions = [x for x in versions if not x.is_prerelease()]
    if not versions:
        return None
    return max(versions).string


def get_sorted_versions(versions, reverse=True, stable=False):
    versions = sorted(map(Version, versions), reverse=reverse)
    if stable:
        versions = [x for x in versions if not x.is_prerelease()]
    return [x.string for x in versions]


def is_archive_of_project(basename, targetname):
    nameversion, ext = splitext_archive(basename)
    # we don't check for strict equality because pypi currently
    # shows "x-docs-1.0.tar.gz" for targetname "x" (however it was uploaded)
    if not normalize_name(nameversion).startswith(targetname):
        return False
    return ext.lower() in ALLOWED_ARCHIVE_EXTS


class Requirement(BaseRequirement):
    @property
    def project_name(self):
        return self.name

    @property
    def specs(self):
        return [
            (spec.operator, spec.version)
            for spec in self.specifier._specs]

    def __contains__(self, version):
        return self.specifier.contains(version)


def parse_requirement(s):
    req = Requirement(s)
    req.specifier.prereleases = True
    return req
