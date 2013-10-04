import sys
import posixpath
if sys.version_info >= (3, 0):
    from urllib import parse as urlp
else:
    import urlparse as urlp

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

def parselinks(htmlcontent, indexurl):
    from devpi_common.vendor._pip import HTMLPage
    page = HTMLPage(htmlcontent, indexurl)
    return list(page.links)
