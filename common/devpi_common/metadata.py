import posixpath
import re
import py
from pkg_resources import parse_version, Requirement
from .types import CompareMixin
from .validation import normalize_name


ALLOWED_ARCHIVE_EXTS = set(
    ".dmg .deb .msi .rpm .exe .egg .whl .tar.gz "
    ".tar.bz2 .tar .tgz .zip .doc.zip".split())


_releasefile_suffix_rx = re.compile(r"(\.zip|\.tar\.gz|\.tgz|\.tar\.bz2|"
    "\.doc\.zip|"
    "\.macosx-\d+.*|"
    "\.linux-.*|"
    "\.[^\.]*\.rpm|"
    "\.win-amd68-py[23]\.\d\..*|"
    "\.win32-py[23]\.\d\..*|"
    "\.win.*\..*|"
    "-(?:py|cp|ip|pp|jy)[23][\d\.]*.*\..*|"
    ")$", re.IGNORECASE)

# see also PEP425 for supported "python tags"
_pyversion_type_rex = re.compile(
        r"(?:py|cp|ip|pp|jy)([\d\.py]+).*\.(exe|egg|msi|whl)", re.IGNORECASE)
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
    _,_,suffix = splitbasename(basename)
    if suffix in (".zip", ".tar.gz", ".tgz", "tar.bz2"):
        return ("source", "sdist")
    m = _pyversion_type_rex.search(suffix)
    if not m:
        return ("any", "bdist_dumb")
    pyversion, ext = m.groups()
    if pyversion == "2.py3":  # "universal" wheel with no C
        pyversion = "2.7"  # arbitrary but pypi/devpi makes no special use
                           # of "pyversion" anyway?!
    elif "." not in pyversion:
        assert len(pyversion) > 0
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
        self.cmpval = parse_version(versionstring)

    def __str__(self):
        return self.string

    def is_prerelease(self):
        for x in self.cmpval:
            if x.startswith('*') and x < '*final':
                return True
        return False


class BasenameMeta(CompareMixin):
    def __init__(self, obj, sameproject=False):
        self.obj = obj
        basename = getattr(obj, "basename", obj)
        if not isinstance(basename, py.builtin._basestring):
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
        return "<BasenameMeta name=%r version=%r>" %(self.name, self.version)

def sorted_sameproject_links(links):
    s = sorted((BasenameMeta(link, sameproject=True)
                     for link in links), reverse=True)
    return [x.obj for x in s]

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


def parse_requirement(s):
    return Requirement.parse(s)
