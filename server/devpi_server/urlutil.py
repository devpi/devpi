
import os, sys
import posixpath
import re
import pkg_resources

if sys.version_info >= (3, 0):
    from urllib.parse import urlparse, urlunsplit, urljoin
else:
    from urlparse import urlparse, urlunsplit, urljoin

def joinpath(url, *args):
    new = url
    for arg in args[:-1]:
        new = urljoin(new, arg) + "/"
    new = urljoin(new, args[-1])
    return new

_releasefile_suffix_rx = re.compile(r"(\.egg|\.zip|\.tar\.gz|\.tgz|\.tar\.bz2|-py[23]\.\d-.*|\.win-amd64-py[23]\.\d\..*|\.win32-py[23]\.\d\..*)$", re.IGNORECASE)

def splitbasename(path, suffix=True):
    """ return (pkgname, version, suffix) triple from basename of path/url. """
    path = posixpath.basename(path)
    pkgname = re.split(r"-\d+", path, 1)[0]
    version = path[len(pkgname) + 1:]
    if suffix:
        m = _releasefile_suffix_rx.search(version)
        assert m, path
        suffix = m.group(1)
        version = version[:-len(suffix)]
    else:
        suffix = ""
        version = _releasefile_suffix_rx.sub("", version)
    return pkgname, version, suffix

class DistURL:
    def __init__(self, url):
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
    def url_nofrag(self):
        return self.geturl_nofragment().url

    @property
    def pkgname_and_version(self):
        return splitbasename(self.basename, suffix=True)[:2]

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
        base, ext = posixpath.splitext(self.basename)
        if base.lower().endswith('.tar'):
            ext = base[-4:] + ext
            base = base[:-4]
        return base, ext

    @property
    def _parsed(self):
        try:
            return self.__parsed
        except AttributeError:
            self.__parsed = p = urlparse(self.url)
            return self.__parsed

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

    def joinpath(self, url):
        newurl = joinpath(self.url, url)
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
