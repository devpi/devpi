from devpi_common.s_url import DistURL
from devpi_common.metadata import splitbasename, Version
import requests

class LinkSet:
    def __init__(self, links):
        self.links = links

    def getnewestversion(self, pkgname):
        best = None
        for link in self.links:
            basename = DistURL(link.url).basename
            name, version = splitbasename(basename)[:2]
            ver = Version(version)
            if name == pkgname:
                if best is None or ver > best[0]:
                    best = ver, link
        return best and best[1] or None

class RemoteIndex:
    class ReceiveError(Exception):
        """ error in receiving remote content. """

    def __init__(self, current):
        self.current = current
        self.requests = requests.Session()

    def getlinkset(self, pkgname):
        """ return list of links for given package. """
        indexurl = DistURL(self.current.simpleindex, pkgname, asdir=1).url
        try:
            content = self.getcontent(indexurl)
        except self.ReceiveError:
            return LinkSet([])
        return LinkSet(parselinks(content, indexurl))

    def getcontent(self, url):
        r = self.requests.get(url)
        if r.status_code != 200:
            raise self.ReceiveError(r.status_code)
        return r.content

    def getbestlink(self, pkgname):
        return self.getlinkset(pkgname).getnewestversion(pkgname)

def parselinks(htmlcontent, indexurl):
    from devpi_common.vendor._pip import HTMLPage
    page = HTMLPage(htmlcontent, indexurl)
    return list(page.links)
