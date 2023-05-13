
import posixpath
from devpi_common.types import cached_property, ensure_unicode, parse_hash_spec
from requests.models import parse_url

from urllib.parse import parse_qs, parse_qsl
from urllib.parse import urlencode, urlparse, urlunsplit, urljoin, unquote


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

    def __str__(self):
        return self.url

    def __repr__(self):
        cloaked = self
        if self.password:
            cloaked = self.replace(password="****")
        cloaked = repr(cloaked.url.encode("utf8"))
        cloaked = cloaked.lstrip("b")
        return "%s(%s)" % (self.__class__.__name__, cloaked)

    def __eq__(self, other):
        return self.url == getattr(other, "url", other)

    def __ne__(self, other):
        return not (self == other)

    def geturl_nofragment(self):
        """ return url without fragment """
        return self.replace(fragment="")

    @cached_property
    def parsed_hash_spec(self):
        return parse_hash_spec(self.fragment)

    @cached_property
    def hash_spec(self):
        hashalgo, hash_value = self.parsed_hash_spec
        if hashalgo:
            return "%s=%s" % (self.hash_type, hash_value)
        return ""

    @cached_property
    def hash_type(self):
        hashalgo, hash_value = self.parsed_hash_spec
        if hashalgo:
            return self.fragment.split("=")[0]

    @cached_property
    def hash_algo(self):
        return parse_hash_spec(self.fragment)[0]

    @cached_property
    def hash_value(self):
        return parse_hash_spec(self.fragment)[1]

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

    @cached_property
    def netloc(self):
        return self._parsed.netloc

    @cached_property
    def username(self):
        return self._parsed.username

    @cached_property
    def password(self):
        return self._parsed.password

    @cached_property
    def hostname(self):
        return self._parsed.hostname

    @cached_property
    def port(self):
        return self._parsed.port

    @cached_property
    def scheme(self):
        return self._parsed.scheme

    @cached_property
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

    @cached_property
    def path(self):
        return self._parsed.path

    @cached_property
    def query(self):
        return self._parsed.query

    def get_query_dict(self, *args, **kwargs):
        return parse_qs(self.query, *args, **kwargs)

    def get_query_items(self, *args, **kwargs):
        return parse_qsl(self.query, *args, **kwargs)

    @cached_property
    def basename(self):
        return posixpath.basename(unquote(self._parsed.path))

    @cached_property
    def parentbasename(self):
        return posixpath.basename(posixpath.dirname(unquote(self._parsed.path)))

    @cached_property
    def fragment(self):
        return self._parsed.fragment

    @cached_property
    def eggfragment(self):
        frag = self.fragment
        if frag.startswith("egg="):
            return frag[4:]

    @cached_property
    def md5(self):
        val = self.fragment
        if val.startswith("md5="):
            return ensure_unicode(val[4:])

    @cached_property
    def sha256(self):
        val = self.fragment
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
            prefix = "../" * (len(parts1) - i - 1)
            return prefix + "/".join(parts2[i:])
        rest = parts2[len(parts1):]
        if parts1[-1]:  # ends not in slash
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
