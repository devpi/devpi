"""
Code taken from pip's index.py for scraping links

note XXX for changes:
- clean_link() is not applied

"""
import re
from devpi_common.url import urljoin

class HTMLPage(object):
    """Represents one page, along with its URL"""

    ## FIXME: these regexes are horrible hacks:
    _homepage_re = re.compile(r'<th>\s*home\s*page', re.I)
    _download_re = re.compile(r'<th>\s*download\s+url', re.I)
    ## These aren't so aweful:
    _rel_re = re.compile("""<[^>]*\srel\s*=\s*['"]?([^'">]+)[^>]*>""", re.I)
    _href_re = re.compile('href=(?:"([^"]*)"|\'([^\']*)\'|([^>\\s\\n]*))', re.I|re.S)
    _base_re = re.compile(r"""<base\s+href\s*=\s*['"]?([^'">]+)""", re.I)

    def __init__(self, content, url, headers=None):
        self.content = content
        self.url = url
        self.headers = headers

    def __str__(self):
        return self.url


    @property
    def base_url(self):
        if not hasattr(self, "_base_url"):
            match = self._base_re.search(self.content)
            if match:
                self._base_url = match.group(1)
            else:
                self._base_url = self.url
        return self._base_url

    @property
    def links(self):
        """Yields all links in the page"""
        for match in self._href_re.finditer(self.content):
            url = match.group(1) or match.group(2) or match.group(3)
            # CHANGED from PIP original: catch parsing errors
            try:
                url = self.clean_link(urljoin(self.base_url, url))
            except ValueError:
                continue
            yield Link(url, self)

    def rel_links(self, rels=('homepage', 'download')):
        for url in self.explicit_rel_links(rels):
            yield url
        for url in self.scraped_rel_links():
            yield url

    def explicit_rel_links(self, rels=('homepage', 'download')):
        """Yields all links with the given relations"""
        for match in self._rel_re.finditer(self.content):
            found_rels = match.group(1).lower().split()
            for rel in rels:
                if rel in found_rels:
                    break
            else:
                continue
            match = self._href_re.search(match.group(0))
            if not match:
                continue
            url = match.group(1) or match.group(2) or match.group(3)
            url = self.clean_link(urljoin(self.base_url, url))
            yield Link(url, self)

    def scraped_rel_links(self):
        for regex in (self._homepage_re, self._download_re):
            match = regex.search(self.content)
            if not match:
                continue
            href_match = self._href_re.search(self.content, pos=match.end())
            if not href_match:
                continue
            url = href_match.group(1) or href_match.group(2) or href_match.group(3)
            if not url:
                continue
            url = self.clean_link(urljoin(self.base_url, url))
            yield Link(url, self)

    _clean_re = re.compile(r'[^a-z0-9$&+,/:;=?@.#%_\\|-]', re.I)

    def clean_link(self, url):
        """Makes sure a link is fully encoded.  That is, if a ' ' shows up in
        the link, it will be rewritten to %20 (while not over-quoting
        % or other characters)."""
        # XXX CHANGE from PIP ORIGINAL
        return url
        return self._clean_re.sub(
            lambda match: '%%%2x' % ord(match.group(0)), url)


class Link(object):

    def __init__(self, url, comes_from=None):
        self.url = url
        self.comes_from = comes_from

    def __str__(self):
        if self.comes_from:
            return '%s (from %s)' % (self.url, self.comes_from)
        else:
            return str(self.url)

    def __repr__(self):
        return '<Link %s>' % self

