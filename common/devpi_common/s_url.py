
import sys
import posixpath
import re
import pkg_resources
from devpi_common.types import cached_property, CompareMixin
from .validation import normalize_name
from requests.models import parse_url
from logging import getLogger
log = getLogger(__name__)

ALLOWED_ARCHIVE_EXTS = set(
    ".dmg .deb .msi .rpm .exe .egg .whl .tar.gz .tar.bz2 .tar .tgz .zip".split())

if sys.version_info >= (3, 0):
    from urllib.parse import urlparse, urlunsplit, urljoin
else:
    from urlparse import urlparse, urlunsplit, urljoin

from pkg_resources import parse_version

def _joinpath(url, args, asdir=False):
    new = url
    for arg in args[:-1]:
        new = urljoin(new, arg) + "/"
    new = urljoin(new, args[-1])
    if asdir:
        new = new.rstrip("/") + "/"
    return new

_releasefile_suffix_rx = re.compile(r"(\.zip|\.tar\.gz|\.tgz|\.tar\.bz2|"
    "\.macosx-\d+.*|"
    "\.linux-.*|"
    "\.[^\.]*\.rpm|"
    "\.win-amd68-py[23]\.\d\..*|"
    "\.win32-py[23]\.\d\..*|"
    "\.win.*\..*|"
    "-(?:py|cp|ip|pp|jy)[23][\d\.]+.*\..*|"
    ")$", re.IGNORECASE)

def sorted_by_version(versions, attr=None):
    parse_version = pkg_resources.parse_version
    if attr:
        def ver(x):
            return parse_version(getattr(x, attr))
    else:
        ver = parse_version
    def vercmp(x, y):
        return cmp(ver(x), ver(y))
    return sorted(versions, cmp=vercmp)

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
    assert m, suffix
    pyversion, ext = m.groups()
    if pyversion == "2.py3":  # "universal" wheel with no C
        pyversion = "2.7"  # arbitrary but pypi/devpi makes no special use
                           # of "pyversion" anyway?!
    elif "." not in pyversion:
        assert len(pyversion) == 2
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
        raise ValueError("invalide archive type %r in: %s" %(ext, path))
    if len(parts) == 1:  # no version
        return projectname, "", ext
    non_projectname = nameversion[len(projectname)+1:] + ext
    # now version might contain platform specifiers
    m = _releasefile_suffix_rx.search(non_projectname)
    assert m, (path, non_projectname)
    suffix = m.group(1)
    version = non_projectname[:-len(suffix)]
    return projectname, version, suffix

def splitext_archive(basename):
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

def get_latest_version(seq):
    return max(map(Version, seq))

class DistURL:
    def __init__(self, url, *args, **kwargs):
        if args:
            url = _joinpath(url, args, **kwargs)
        self.url = url

    def __repr__(self):
        return "<DistURL url=%r>" % (self.url, )

    def __eq__(self, other):
        return self.url == getattr(other, "url", other)

    def geturl_nofragment(self):
        """ return url without fragment """
        scheme, netloc, url, params, query, ofragment = self._parsed
        return DistURL(urlunsplit((scheme, netloc, url, query, "")))

    @property
    def scheme(self):
        return self._parsed.scheme

    def is_archive_of_project(self, targetname):
        nameversion, ext = self.splitext_archive()
        # we don't check for strict equality because pypi currently
        # shows "x-docs-1.0.tar.gz" for targetname "x" (however it was uploaded)
        if not normalize_name(nameversion).startswith(targetname):
            return False
        if ext.lower() not in ALLOWED_ARCHIVE_EXTS:
            return False
        if self.is_valid_http_url():
            return True
        log.warn("url cannot be parsed or is unsupported: %r", self)
        return False

    @property
    def url_nofrag(self):
        return self.geturl_nofragment().url

    @property
    def pkgname_and_version(self):
        return splitbasename(self.basename)[:2]

    @property
    def easyversion(self):
        if self.eggfragment:
            return ('9' * 8, '*@')
        return pkg_resources.parse_version(self.pkgname_and_version[1])

    def __cmp__(self, other):
        """ sorting as defined by UpstreamCache.getpackagelinks() """
        return cmp(self.easyversion, other.easyversion)

    def __hash__(self):
        return hash(self.url)

    def splitext_archive(self):
        return splitext_archive(self.basename)

    @cached_property
    def _parsed(self):
        return urlparse(self.url)

    def is_valid_http_url(self):
        try:
            x = parse_url(self.url)
        except Exception:
            return False
        return x.scheme in ("http", "https")

    @property
    def path(self):
        return self._parsed.path

    @property
    def basename(self):
        return posixpath.basename(self._parsed.path)

    @property
    def parentbasename(self):
        return posixpath.basename(posixpath.dirname(self._parsed.path))

    @property
    def eggfragment(self):
        frag = self._parsed.fragment
        if frag.startswith("egg="):
            return frag[4:]

    @property
    def md5(self):
        val = self._parsed.fragment
        if val.startswith("md5="):
            return val[4:]

    def joinpath(self, *args, **kwargs):
        newurl = _joinpath(self.url, args, **kwargs)
        return DistURL(newurl)

    def torelpath(self):
        """ return scheme/netloc/path/fragment into a canonical relative
        filepath.  Only the scheme, netlocation and path are mapped,
        fragments and queries are ignored.
        """
        parsed = self._parsed
        assert parsed.scheme in ("http", "https")
        return "%s/%s%s" % (parsed.scheme, parsed.netloc, parsed.path)

    @classmethod
    def fromrelpath(cls, relpath):
        """ return url from canonical relative path. """
        scheme, netlocpath = relpath.split("/", 1)
        return cls(scheme + "://" + netlocpath)

