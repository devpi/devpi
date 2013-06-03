import pkg_resources
from devpi.util.version import guess_pkgname_and_version
from devpi.util import url as urlutil
import requests

class LinkSet:
    def __init__(self, links):
        self.links = links

    def getnewestversion(self, pkgname):
        best = None
        for link in self.links:
            name, version = guess_pkgname_and_version(link.basename)
            if name != pkgname:
                continue
            if best is None or version > best[0]:
                best = version, link
        return best and best[1] or None

class RemoteIndex:
    class ReceiveError(Exception):
        """ error in receiving remote content. """

    def __init__(self, config):
        self.config = config
        self.requests = requests.Session()

    def getlinkset(self, pkgname):
        """ return list of links for given package. """
        indexurl = urlutil.joinpath(self.config.simpleindex, pkgname + "/")
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

    def getindexconfig(self, indexname):
        r = self.getcontent(self.config.indexadmin)



def parselinks(htmlcontent, indexurl=None):
    l = []
    for link in urlutil.parselinks(htmlcontent):
        parts = link.href.split("#md5=", 1)
        if len(parts) > 1:
            link.href, link.md5 = parts
        else:
            link.md5 = None
        if indexurl is not None:
            link.href = urlutil.joinpath(indexurl, link.href)
        l.append(link)
    return l
