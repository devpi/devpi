import posixpath
from .url import URL

class ViewLinkStore:
    def __init__(self, url, versiondata):
        self.url = URL(url)
        self.versiondata = versiondata

    def get_links(self, rel=None, for_href=None, basename=None):
        l = []
        for linkdict in self.versiondata.get("+links", []):
            viewlink = ViewLink(self.url, linkdict)
            if (not rel or viewlink.rel == rel) and \
               (not for_href or viewlink.for_href==for_href) and \
               (not basename or viewlink.basename == basename):
                l.append(viewlink)
        return l

    def get_link(self, rel=None, basename=None, for_href=None):
        links = self.get_links(rel=rel, basename=basename, for_href=for_href)
        assert len(links) == 1
        return links[0]

    def shadowed(self):
        l = []
        for verdata in self.versiondata.get("+shadowing", []):
            l.append(ViewLinkStore(self.url.url, verdata))
        return l


class ViewLink:
    def __init__(self, base_url, linkdict):
        self.__dict__.update(linkdict)
        self.href = base_url.joinpath(self.href).url
        self.basename = posixpath.basename(self.href)

    def __repr__(self):
        return "<ViewLink rel=%r href=%r>" %(self.rel, self.href)

