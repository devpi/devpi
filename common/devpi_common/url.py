
import sys
import posixpath
from devpi_common.types import cached_property
from requests.models import parse_url

if sys.version_info >= (3, 0):
    from urllib.parse import urlparse, urlunsplit, urljoin
else:
    from urlparse import urlparse, urlunsplit, urljoin

def _joinpath(url, args, asdir=False):
    new = url
    for arg in args[:-1]:
        new = urljoin(new, arg) + "/"
    new = urljoin(new, args[-1])
    if asdir:
        new = new.rstrip("/") + "/"
    return new

class URL:
    def __init__(self, url="", *args, **kwargs):
        if isinstance(url, URL):
            url = url.url
        if args:
            url = _joinpath(url, args, **kwargs)
        self.url = url

    def __nonzero__(self):
        return bool(self.url)

    __bool__ = __nonzero__

    def __repr__(self):
        return "<URL url=%r>" % (self.url, )

    def __eq__(self, other):
        return self.url == getattr(other, "url", other)

    def geturl_nofragment(self):
        """ return url without fragment """
        scheme, netloc, url, params, query, ofragment = self._parsed
        return URL(urlunsplit((scheme, netloc, url, query, "")))

    @property
    def scheme(self):
        return self._parsed.scheme

    @property
    def url_nofrag(self):
        return self.geturl_nofragment().url

    def __hash__(self):
        return hash(self.url)

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
        return URL(newurl)

    def addpath(self, *args, **kwargs):
        url = self.url.rstrip("/") + "/"
        return URL(_joinpath(url, args, **kwargs))

    def asdir(self):
        if self.url[-1:] == "/":
            return self
        return self.__class__(self.url + "/")

    def asfile(self):
        if self.url[-1:] == "/":
            return self.__class__(self.url.rstrip("/"))
        return self

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

