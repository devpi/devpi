import sys
import posixpath
if sys.version_info >= (3, 0):
    from urllib import parse as urlp
else:
    import urlparse as urlp

from bs4 import BeautifulSoup

def urlparse(url):
    return urlp.urlparse(url)

def urlunsplit(tupledata):
    return urlp.urlunsplit(tupledata)

def is_valid_url(url):
    result = urlparse(url)
    if result.scheme not in ("http", "https"):
        return False
    if not result.netloc or result.netloc.endswith(":"):
        return False
    return True

def joinpath(url, *args):
    new = url
    for arg in args[:-1]:
        new = urlp.urljoin(new, arg) + "/"
    new = urlp.urljoin(new, args[-1])
    return new

def getnetloc(url, scheme=False):
    parsed = urlparse(url)
    netloc = parsed.netloc
    if netloc.endswith(":80"):
        netloc = netloc[:-3]
    if scheme:
        netloc = "%s://%s" %(parsed.scheme, netloc)
    return netloc

def ishttp(url):
    parsed = urlparse(url)
    return parsed.scheme in ("http", "https") and parsed.netloc

def getscheme(url):
    return urlparse(url).scheme

def getpath(url):
    return urlparse(url).path

def url2path(url):
    """ return scheme/netloc/path into a canonical relative filepath.
    Only the scheme, netlocation and path are mapped, queries or fragments
    are ignored.
    """
    parsed = urlparse(url)
    assert parsed.scheme.startswith("http")
    return "%s/%s%s" % (parsed.scheme, parsed.netloc, parsed.path)

def path2url(relpath):
    """ return url from canonical relative path. """
    scheme, netlocpath = relpath.split("/", 1)
    return scheme + "://" + netlocpath

def parselinks(htmlcontent, indexurl=None):
    soup = BeautifulSoup(htmlcontent)
    return list(map(A, soup.findAll("a")))

class A:
    def __init__(self, a):
        self.href = a.get("href")
        self.rel = a.get("rel", [])
        self.text = a.text and a.text.strip() or ""

    @property
    def basename(self):
        return posixpath.basename(self.href)

    def __str__(self):
        return "<A href=%r rel=%r text=%r>" % (self.href, self.rel, self.text)
