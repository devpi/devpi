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

#wheel_file_re = re.compile(
#                r"""^(?P<namever>(?P<name>.+?)(-(?P<ver>\d.+?))?)
#                ((-(?P<build>\d.*?))?-(?P<pyver>.+?)-(?P<abi>.+?)-(?P<plat>.+?)
#                \.whl|\.dist-info)$""",
#                re.VERBOSE)

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
        assert len(pyversion) in (1, 2)  # TODO: do we really care?
        pyversion = ".".join(pyversion)
    return (pyversion, _ext2type[ext])

def splitbasename(path, checkarch=True):
    nameversion, ext = splitext_archive(path)
    parts = re.split(r'-\d+', nameversion)
    projectname = parts[0]
    if not projectname:
        raise ValueError("could not identify projectname in path: %s" %
                         path)
    if checkarch and ext.lower() not in ALLOWED_ARCHIVE_EXTS:
        raise ValueError("invalid archive type %r in: %s" %(ext, path))
    if len(parts) == 1:  # no version
        return projectname, "", ext
    non_projectname = nameversion[len(projectname)+1:] + ext
    # now version might contain platform specifiers
    m = _releasefile_suffix_rx.search(non_projectname)
    assert m, (path, non_projectname)
    suffix = m.group(1)
    version = non_projectname[:-len(suffix)]
    return projectname, version, suffix

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
