
import pytest
from devpi_server.extpypi import (DistURL, parse_index, HTTPCacheAdapter,
     FileSystemCache)

class TestDistURL:
    def test_basename(self):
        d = DistURL("http://codespeak.net/basename")
        assert d.basename == "basename"
        d = DistURL("http://codespeak.net")
        assert not d.basename

    def test_parentbasename(self):
        d = DistURL("http://codespeak.net/simple/basename/")
        assert d.parentbasename == "basename"
        assert d.basename == ""

    def test_hashing(self):
        assert hash(DistURL("http://a")) == hash(DistURL("http://a"))
        assert DistURL("http://a") == DistURL("http://a")

    def test_eggfragment(self):
        url = DistURL("http://a/py.tar.gz#egg=py-dev")
        assert url.eggfragment == "py-dev"

class TestParser:
    simplepy = DistURL("http://pypi.python.org/simple/py/")

    def test_parse_index_simple(self):
        result = parse_index(self.simplepy,
            """<a href="../../pkg/py-1.4.12.zip#md5=12ab">qwe</a>""")
        link, = result.releaselinks
        assert link.basename == "py-1.4.12.zip"
        assert link.md5 == "12ab"

    @pytest.mark.parametrize("rel", ["homepage", "download"])
    def test_parse_index_with_rel(self, rel):
        result = parse_index(self.simplepy, """
               <a href="http://pylib.org" rel="%s">whatever</a>
               <a href="http://pylib2.org" rel="%s">whatever2</a>
               <a href="http://pylib3.org">py-1.0.zip</a>
               <a href="http://pylib2.org/py-1.0.zip" rel="%s">whatever2</a>
        """ % (rel,rel, rel))
        assert len(result.releaselinks) == 1
        assert result.releaselinks[0] == "http://pylib2.org/py-1.0.zip"
        assert len(result.scrapelinks) == 2
        assert result.scrapelinks[0] == "http://pylib.org"
        assert result.scrapelinks[1] == "http://pylib2.org"

    def test_parse_index_with_egg(self):
        # XXX re-check with exact setuptools egg parsing logic
        result = parse_index(self.simplepy,
            """<a href="http://bitbucket.org/download/py-dev#egg=dev" /a>""")
        assert len(result.releaselinks) == 1
        link, = result.releaselinks
        assert link.basename == "py-dev"
        assert link.eggfragment == "dev"

    def test_releasefile_and_scrape(self):
        result = parse_index(self.simplepy,
            """<a href="../../pkg/py-1.4.12.zip#md5=12ab">qwe</a>
               <a href="http://pylib.org" rel="homepage">whatever</a>
               <a href="http://pylib2.org" rel="download">whatever2</a>
        """)
        assert len(result.releaselinks) == 1
        assert len(result.scrapelinks) == 2
        result.parse_index(result.scrapelinks[0], """
               <a href="http://pylib.org/py-1.1.zip" /a>
               <a href="http://pylib.org/other" rel="download" /a>
        """, scrape=False)
        assert len(result.scrapelinks) == 2
        assert len(result.releaselinks) == 2
        assert result.releaselinks[1] == "http://pylib.org/py-1.1.zip"


class SimpleCache(dict):
    set = dict.__setitem__

class TestHTTPCacheAdapter:
    def test_httpcacheget_ok(self):
        class httpget:
            def __init__(self, url):
                self.url = url
                self.status_code = 200
                self.text = "hello"
        httpcache = HTTPCacheAdapter(SimpleCache(), httpget)
        text = httpcache.gethtml("http://hello")
        del httpcache.httpget
        assert text == "hello"
        assert httpcache.gethtml("http://hello") == "hello"

    def test_httpcacheget_redirect_ok(self):
        class httpget:
            def __init__(self, url):
                self.url = url
                if url == "http://hello/world":
                    self.status_code = 301
                    self.headers = {"location": "/redirect"}
                elif url == "http://hello/redirect":
                    self.status_code = 200
                    self.text = "redirected"
                else:
                    assert 0
        httpcache = HTTPCacheAdapter(SimpleCache(), httpget)
        text = httpcache.gethtml("http://hello/world")
        assert text == "redirected"
        del httpcache.httpget
        assert httpcache.gethtml("http://hello/world") == "redirected"

    def test_httpcacheget_redirect_max(self):
        class httpget:
            def __init__(self, url):
                self.url = url
                self.headers = {"location": "/redirect"}
                self.status_code = 301
        httpcache = HTTPCacheAdapter(SimpleCache(), httpget)
        assert httpcache.gethtml("whatever") == 301

class TestFileSystemCache:

    @pytest.mark.parametrize("item", [
        "something",
        [301, "redirect"],
        {"code": 301, "content": "hello"},
        404,
    ])
    def test_getset_text(self, tmpdir, item):
        cache = FileSystemCache(tmpdir)
        assert cache.get("http://whatever/this") is None
        cache.set("http://whatever/this", item)
        assert cache.get("http://whatever/this") == item

