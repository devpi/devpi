import pkg_resources
from devpi_common.url import URL
from devpi_common.metadata import splitbasename, Version
from devpi_common.request import new_requests_session
from devpi import __version__ as client_version

class LinkSet:
    def __init__(self, links):
        self.links = links

    def getnewestversion(self, pkgname):
        """ returns newest applicable version of package """
        req = next(pkg_resources.parse_requirements(pkgname))
        best = None
        for link in self.links:
            basename = URL(link.url).basename
            name, version = splitbasename(basename)[:2]
            ver = Version(version)
            if name in (req.project_name, pkgname) and version in req:
                if best is None or ver > best[0]:
                    best = ver, link
        return best and best[1] or None

class RemoteIndex:
    class ReceiveError(Exception):
        """ error in receiving remote content. """

    def __init__(self, current):
        self.current = current
        self.requests = new_requests_session(agent=("client", client_version))

    def getlinkset(self, pkgname):
        """ return list of links for given package. """
        req = next(pkg_resources.parse_requirements(pkgname))
        indexurl = URL(self.current.simpleindex, req.project_name, asdir=1).url
        try:
            (indexurl, content) = self.getcontent(indexurl)
        except self.ReceiveError:
            return LinkSet([])
        return LinkSet(parselinks(content, indexurl))

    def getcontent(self, url, bytes=False):
        r = self.requests.get(url)
        if r.status_code != 200:
            raise self.ReceiveError(r.status_code)
        if bytes:
            return (r.request.url, r.content)
        else:
            return (r.request.url, r.text)

    def getbestlink(self, pkgname):
        return self.getlinkset(pkgname).getnewestversion(pkgname)

def parselinks(htmlcontent, indexurl):
    from devpi_common.vendor._pip import HTMLPage
    page = HTMLPage(htmlcontent, indexurl)
    return list(page.links)
