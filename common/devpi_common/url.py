import sys
import posixpath
from devpi_common.types import cached_property, ensure_unicode, parse_hash_spec
from requests.models import parse_url

if sys.version_info >= (3, 0):
    from urllib.parse import parse_qs, parse_qsl
    from urllib.parse import urlencode, urlparse, urlunsplit, urljoin, unquote
else:
    from urlparse import parse_qs, parse_qsl
    from urlparse import urlparse, urlunsplit, urljoin
    from urllib import urlencode, unquote


def _joinpath(url, args, asdir=False):
    url = URL(url)
    query = url.query
    url = url.replace(query="").url
    new = url
    for arg in args[:-1]:
        new = urljoin(new, arg.rstrip("/")) + "/"
    new = urljoin(new, args[-1])
    if asdir:
        new = new.rstrip("/") + "/"
    return URL(new).replace(query=query).url


class URL:
    def __init__(self, url="", *args, **kwargs):
        if isinstance(url, URL):
            url = url.url
        if args:
            url = _joinpath(url, args, **kwargs)
        if not url:
            url = ""
        self.url = ensure_unicode(url)

    def __nonzero__(self):
        return bool(self.url)

    __bool__ = __nonzero__

    def __repr__(self):
        cloaked = self
        if self.password:
            cloaked = self.replace(password="****")
        cloaked = repr(cloaked.url.encode("utf8"))
        if sys.version_info >= (3,0):
            cloaked = cloaked.lstrip("b")
        return "URL(%s)" % cloaked

    def __eq__(self, other):
        return self.url == getattr(other, "url", other)

    def __ne__(self, other):
        return not (self == other)

    def geturl_nofragment(self):
        """ return url without fragment """
        scheme, netloc, url, params, query, ofragment = self._parsed
        return URL(urlunsplit((scheme, netloc, url, query, "")))

    @property
    def hash_spec(self):
        hashalgo, hash_value = parse_hash_spec(self._parsed[-1])
        if hashalgo:
            hashtype = self._parsed[-1].split("=")[0]
            return "%s=%s" %(hashtype, hash_value)
        return ""

    @property
    def hash_algo(self):
        return parse_hash_spec(self._parsed[-1])[0]

    @property
    def hash_value(self):
        return parse_hash_spec(self._parsed[-1])[1]

    def replace(self, **kwargs):
        _parsed = self._parsed
        url = []
        if set(kwargs).intersection(('username', 'password', 'hostname', 'port')):
            netloc = ""
            if "username" in kwargs:
                if kwargs["username"]:
                    netloc += kwargs["username"]
            elif self.username:
                netloc += self.username
            if "password" in kwargs:
                if kwargs["password"]:
                    netloc += ":" + kwargs["password"]
            elif self.password:
                netloc += ":" + self.password
            if netloc:
                netloc += "@"
            if "hostname" in kwargs:
                if not kwargs["hostname"]:
                    raise ValueError("Can't use empty 'hostname'.")
                netloc += kwargs["hostname"]
            else:
                if self.hostname:
                    netloc += self.hostname
            if "port" in kwargs:
                if kwargs["port"]:
                    netloc += ":%s" % kwargs["port"]
            elif self.port:
                netloc += ":%s" % self.port
            if netloc != self.netloc:
                if "netloc" in kwargs:
                    raise ValueError(
                        "Can't use 'netloc' together with any of "
                        "'username', 'password', 'hostname', 'port'.")
                kwargs["netloc"] = netloc
        for field in ('scheme', 'netloc', 'path', 'query', 'fragment'):
            value = kwargs.get(field, getattr(_parsed, field))
            if field == 'query':
                try:
                    value = urlencode(value)
                except TypeError:
                    pass
            url.append(value)
        return URL(urlunsplit(url))

    @property
    def netloc(self):
        return self._parsed.netloc

    @property
    def username(self):
        return self._parsed.username

    @property
    def password(self):
        return self._parsed.password

    @property
    def hostname(self):
        return self._parsed.hostname

    @property
    def port(self):
        return self._parsed.port

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
    def query(self):
        return self._parsed.query

    def get_query_dict(self, *args, **kwargs):
        return parse_qs(self.query, *args, **kwargs)

    def get_query_items(self, *args, **kwargs):
        return parse_qsl(self.query, *args, **kwargs)

    @property
    def basename(self):
        return posixpath.basename(unquote(self._parsed.path))

    @property
    def parentbasename(self):
        return posixpath.basename(posixpath.dirname(unquote(self._parsed.path)))

    @property
    def eggfragment(self):
        frag = self._parsed.fragment
        if frag.startswith("egg="):
            return frag[4:]

    @property
    def md5(self):
        val = self._parsed.fragment
        if val.startswith("md5="):
            return ensure_unicode(val[4:])

    @property
    def sha256(self):
        val = self._parsed.fragment
        if val.startswith("sha256="):
            return ensure_unicode(val[4:])

    def joinpath(self, *args, **kwargs):
        newurl = _joinpath(self.url, args, **kwargs)
        return URL(newurl)

    def addpath(self, *args, **kwargs):
        return URL(_joinpath(self.asdir().url, args, **kwargs))

    def relpath(self, target):
        """ return a relative path which will point to the target resource."""
        parts1 = self.path.split("/")
        parts2 = target.split("/")
        if not parts2 or parts2[0]:
            raise ValueError("not an absolute target: %s" % (target,))
        for i, part in enumerate(parts1):
            if parts2[i] == part:
                continue
            prefix = "../" * (len(parts1)-i-1)
            return prefix + "/".join(parts2[i:])
        rest = parts2[len(parts1):]
        if parts1[-1]: # ends not in slash
            rest.insert(0, parts1[-1])
        return "/".join(rest)

    def asdir(self):
        if self.path[-1:] == "/":
            return self
        return self.replace(path=self.path + "/")

    def asfile(self):
        if self.path[-1:] == "/":
            return self.replace(path=self.path.rstrip("/"))
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
