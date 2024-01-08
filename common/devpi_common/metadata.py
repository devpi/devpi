import posixpath
import re
from packaging.requirements import Requirement as BaseRequirement
from packaging.version import InvalidVersion
from packaging.version import Version as PackagingVersion
from packaging.version import parse as orig_parse_version
from .types import CompareMixin
from .types import cached_property
from .validation import normalize_name


ALLOWED_ARCHIVE_EXTS = set(
    ".dmg .deb .msi .rpm .exe .egg .whl .tar.gz "
    ".tar.bz2 .tar .tgz .zip .doc.zip".split())


class LegacyVersion(object):
    # "naturally" sorted and always smaller than a valid version
    __slots__ = ('_value', 'cmpval')

    def __init__(self, version):
        self._value = version
        self.cmpval = tuple(
            (int(n) if n != '' else 0, a)
            for n, a in re.findall(r'(\d*)([^\d]*)', version))

    def __lt__(self, other):
        if isinstance(other, PackagingVersion):
            # always smaller
            return True
        if isinstance(other, LegacyVersion):
            return self.cmpval < other.cmpval
        return NotImplemented

    def __le__(self, other):
        if isinstance(other, PackagingVersion):
            # always smaller or equal
            return True
        if isinstance(other, LegacyVersion):
            return self.cmpval <= other.cmpval
        return NotImplemented

    def __eq__(self, other):
        if isinstance(other, PackagingVersion):
            # never equal
            return False
        if isinstance(other, LegacyVersion):
            return self.cmpval == other.cmpval
        return NotImplemented

    def __ne__(self, other):
        if isinstance(other, PackagingVersion):
            # never equal
            return True
        if isinstance(other, LegacyVersion):
            return self.cmpval != other.cmpval
        return NotImplemented

    def __ge__(self, other):
        if isinstance(other, PackagingVersion):
            # never greater or equal
            return False
        if isinstance(other, LegacyVersion):
            return self.cmpval >= other.cmpval
        return NotImplemented

    def __gt__(self, other):
        if isinstance(other, PackagingVersion):
            # never greater
            return False
        if isinstance(other, LegacyVersion):
            return self.cmpval > other.cmpval
        return NotImplemented


def parse_version(version):
    try:
        return orig_parse_version(version)
    except InvalidVersion:
        return LegacyVersion(version)


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


class Version(CompareMixin):
    def __init__(self, versionstring):
        self.string = versionstring

    @cached_property
    def cmpval(self):
        return parse_version(self.string)

    def __str__(self):
        return self.string

    def __repr__(self):
        return "Version(%r)" % self.string

    def is_prerelease(self):
        if hasattr(self.cmpval, 'is_prerelease'):
            return self.cmpval.is_prerelease
        # backward compatibility
        for x in self.cmpval:
            if x.startswith('*') and x < '*final':
                return True
        return False


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
    if not seq:
        return
    versions = map(Version, seq)
    if stable:
        versions = [x for x in versions if not x.is_prerelease()]
        if not versions:
            return
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
    if ext.lower() not in ALLOWED_ARCHIVE_EXTS:
        return False
    return True


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
