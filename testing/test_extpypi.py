
import pytest
from devpi_server.extpypi import *
from devpi_server.main import FatalResponse
import mock
import time

class TestIndexParsing:
    simplepy = DistURL("http://pypi.python.org/simple/py/")

    def test_parse_index_simple(self):
        result = parse_index(self.simplepy,
            """<a href="../../pkg/py-1.4.12.zip#md5=12ab">qwe</a>""")
        link, = result.releaselinks
        assert link.basename == "py-1.4.12.zip"
        assert link.md5 == "12ab"

    def test_parse_index_simple_nocase(self):
        simplepy = DistURL("http://pypi.python.org/simple/Py/")
        result = parse_index(simplepy,
            """<a href="../../pkg/py-1.4.12.zip#md5=12ab">qwe</a>
               <a href="../../pkg/PY-1.4.13.zip">qwe</a>
               <a href="../../pkg/pyzip#egg=py-dev">qwe</a>
        """)
        assert len(result.releaselinks) == 3

    def test_parse_index_simple_nomatch(self):
        result = parse_index(self.simplepy,
            """<a href="../../pkg/py-1.3.html">qwe</a>""")
        assert not result.releaselinks

    @pytest.mark.parametrize("rel", ["homepage", "download"])
    def test_parse_index_with_rel(self, rel):
        result = parse_index(self.simplepy, """
               <a href="http://pylib.org" rel="%s">whatever</a>
               <a href="http://pylib2.org" rel="%s">whatever2</a>
               <a href="http://pylib3.org">py-1.0.zip</a>
               <a href="http://pylib2.org/py-1.0.zip" rel="%s">whatever2</a>
        """ % (rel,rel, rel))
        assert len(result.releaselinks) == 1
        link, = result.releaselinks
        assert link == "http://pylib2.org/py-1.0.zip"
        assert len(result.crawllinks) == 2
        assert result.crawllinks == \
                    set(["http://pylib.org", "http://pylib2.org"])

    def test_parse_index_with_egg(self):
        result = parse_index(self.simplepy,
            """<a href="http://bb.org/download/py.zip#egg=py-dev" />
               <a href="http://bb.org/download/py-1.0.zip" />
               <a href="http://bb.org/download/py.zip#egg=something-dev" />
        """)
        assert len(result.releaselinks) == 2
        link, link2 = result.releaselinks
        assert link.basename == "py.zip"
        assert link.eggfragment == "py-dev"
        assert link2.basename == "py-1.0.zip"

    def test_parse_index_with_two_eggs_ordering(self):
        # it seems that pip/easy_install in some cases
        # rely on the exact ordering of eggs in the html page
        # for example with nose, there are two eggs and the second/last
        # one is chosen due to the internal pip/easy_install algorithm
        result = parse_index(self.simplepy,
            """<a href="http://bb.org/download/py.zip#egg=py-dev" />
               <a href="http://other/master#egg=py-dev" />
        """)
        assert len(result.releaselinks) == 2
        link1, link2 = result.releaselinks
        assert link1.basename == "master"
        assert link1.eggfragment == "py-dev"
        assert link2.basename == "py.zip"
        assert link2.eggfragment == "py-dev"

    def test_releasefile_and_scrape(self):
        result = parse_index(self.simplepy,
            """<a href="../../pkg/py-1.4.12.zip#md5=12ab">qwe</a>
               <a href="http://pylib.org" rel="homepage">whatever</a>
               <a href="http://pylib2.org" rel="download">whatever2</a>
        """)
        assert len(result.releaselinks) == 1
        assert len(result.crawllinks) == 2
        result.parse_index(DistURL("http://pylib.org"), """
               <a href="http://pylib.org/py-1.1.egg" />
               <a href="http://pylib.org/other" rel="download" />
        """, scrape=False)
        assert len(result.crawllinks) == 2
        assert len(result.releaselinks) == 2
        links = list(result.releaselinks)
        assert links[0].url == \
                "http://pypi.python.org/pkg/py-1.4.12.zip#md5=12ab"
        assert links[1].url == "http://pylib.org/py-1.1.egg"

    def test_releasefile_md5_matching_and_ordering(self):
        """ check that md5-links win over non-md5 links anywhere.
        And otherwise the links from the index page win over scraped ones.
        """
        result = parse_index(self.simplepy,
            """<a href="../../pkg/py-1.4.12.zip#md5=12ab">qwe</a>
               <a href="../../pkg/py-1.4.11.zip">qwe</a>
               <a href="../../pkg/py-1.4.10.zip#md5=2222">qwe</a>
               <a href="http://pylib.org" rel="homepage">whatever</a>
               <a href="http://pylib2.org" rel="download">whatever2</a>
        """)
        assert len(result.releaselinks) == 3
        assert len(result.crawllinks) == 2
        result.parse_index(DistURL("http://pylib.org"), """
               <a href="http://pylib.org/py-1.4.12.zip" />
               <a href="http://pylib.org/py-1.4.11.zip#md5=1111" />
               <a href="http://pylib.org/py-1.4.10.zip#md5=12ab" />
        """, scrape=False)
        assert len(result.crawllinks) == 2
        assert len(result.releaselinks) == 3
        link1, link2, link3 = result.releaselinks
        assert link1.url == \
                "http://pypi.python.org/pkg/py-1.4.12.zip#md5=12ab"
        assert link2.url == \
                "http://pylib.org/py-1.4.11.zip#md5=1111"
        assert link3.url == \
                "http://pypi.python.org/pkg/py-1.4.10.zip#md5=2222"


class TestHTMLCacheResponse:
    #@pytest.mark.parametrize("item", [
    #    "something",
    #    [301, "redirect"],
    #    {"code": 301, "content": "hello"},
    #    404,
    #])

    def test_basic(self, redis):
        redis.flushdb()
        url = "https://something/simple/pytest/"
        r = HTMLCacheResponse(redis, "cache:" + url, url)
        assert not r
        class PseudoResponse:
            status_code = 200
            text = py.builtin._totext("hello")

        r.setnewreponse(PseudoResponse)
        assert r
        assert r.status_code == 200
        assert r.text == py.builtin._totext("hello")
        assert py.builtin._istext(r.text)

        r = HTMLCacheResponse(redis, "cache:" + url, url)
        assert r
        assert r.status_code == 200
        assert r.text == py.builtin._totext("hello")
        assert py.builtin._istext(r.text)

        r.setnewreponse(FatalResponse())
        r = HTMLCacheResponse(redis, "cache:" + url, url)
        assert r.status_code == 200

    def test_fatal_response_first_is_cached(self, redis):
        redis.flushdb()
        url = "https://something/simple/pytest/"
        r = HTMLCacheResponse(redis, "cache:" + url, url)
        class PseudoResponse:
            status_code = -1
        r.setnewreponse(PseudoResponse)
        assert r
        assert r.status_code == -1

    def test_redirect(self, redis):
        url = "https://something/simple/pytest"
        r = HTMLCacheResponse(redis, "cache:" + url, url)
        assert not r
        class PseudoResponse:
            status_code = 301
            headers = {"location": "/simple/pytest/"}
        r.setnewreponse(PseudoResponse)
        assert r
        assert r.status_code == 301
        assert r.text is None
        assert r.nextlocation == url + "/"

        r = HTMLCacheResponse(redis, "cache:" + url, url)
        assert r
        assert r.status_code == 301
        assert r.text is None
        assert r.nextlocation == url + "/"

class TestHTMLCache:

    @pytest.mark.parametrize("target", ["http://hello", "http://hello/"])
    def test_htmlcacheget_ok(self, redis, target):
        class httpget:
            def __init__(self, url, allow_redirects):
                assert not allow_redirects
                self.url = url
                self.status_code = 200
                self.text = "hello"
        htmlcache = HTMLCache(redis, httpget)
        response = htmlcache.get(target)
        assert response.status_code == 200
        assert response.text == "hello"
        del htmlcache.httpget
        assert htmlcache.get(target).text == "hello"

    def test_htmlcacheget_redirect_ok(self, redis):
        class httpget:
            def __init__(self, url, allow_redirects):
                assert not allow_redirects
                self.url = url
                if url == "http://hello/world":
                    self.status_code = 301
                    self.headers = {"location": "/redirect"}
                elif url == "http://hello/redirect":
                    self.status_code = 200
                    self.text = "redirected"
                else:
                    assert 0
        htmlcache = HTMLCache(redis, httpget)
        text = htmlcache.get("http://hello/world").text
        assert text == "redirected"
        del htmlcache.httpget  # make sure we don't trigger network anymore
        assert htmlcache.get("http://hello/world").text == "redirected"

    def test_htmlcacheget_redirect_max(self, redis):
        class httpget:
            def __init__(self, url, allow_redirects):
                assert not allow_redirects
                self.url = url
                self.headers = {"location": "/redirect"}
                self.status_code = 301
        htmlcache = HTMLCache(redis, httpget)
        assert htmlcache.get("http://whatever") == 301

class TestExtPYPIDB:
    def test_parse_project_nomd5(self, extdb):
        extdb.url2response["https://pypi.python.org/simple/pytest/"] = dict(
            status_code=200,
            text='<a href="../../pkg/pytest-1.0.zip#md5=123" />')
        links = extdb.getreleaselinks("pytest")
        link, = links
        assert link.url == "https://pypi.python.org/pkg/pytest-1.0.zip"
        assert link.md5 == "123"
        assert link.relpath.endswith("/pytest-1.0.zip")

    def test_parse_and_scrape(self, extdb):
        extdb.url2response["https://pypi.python.org/simple/pytest/"] = dict(
            status_code=200, text='''
                <a href="../../pkg/pytest-1.0.zip#md5=123" />
                <a rel="download" href="https://download.com/index.html" />
            ''')
        extdb.url2response["https://download.com/index.html"] = dict(
            status_code=200, text = '''
                <a href="pytest-1.1.tar.gz" />
            ''')
        links = extdb.getreleaselinks("pytest")
        assert len(links) == 2
        assert links[0].url == "https://download.com/pytest-1.1.tar.gz"
        assert links[0].relpath.endswith("/pytest-1.1.tar.gz")

        # check refresh
        extdb.url2response["https://pypi.python.org/simple/pytest/"] = dict(
            status_code=200, text='''
                <a href="../../pkg/pytest-1.0.1.zip#md5=456" />
                <a href="../../pkg/pytest-1.0.zip#md5=123" />
                <a rel="download" href="https://download.com/index.html" />
            ''')
        assert len(extdb.getreleaselinks("pytest")) == 2  # no refresh
        links = extdb.getreleaselinks("pytest", refresh=True)
        assert len(links) == 3
        assert links[1].url == "https://pypi.python.org/pkg/pytest-1.0.1.zip"
        assert links[1].relpath.endswith("/pytest-1.0.1.zip")

    def test_parse_and_scrape_not_found(self, extdb):
        extdb.url2response["https://pypi.python.org/simple/pytest/"] = dict(
            status_code=200, text='''
                <a href="../../pkg/pytest-1.0.zip#md5=123" />
                <a rel="download" href="https://download.com/index.html" />
            ''')
        extdb.url2response["https://download.com/index.html"] = dict(
            status_code=404, text = 'not found')
        links = extdb.getreleaselinks("pytest")
        assert len(links) == 1
        assert links[0].url == \
                "https://pypi.python.org/pkg/pytest-1.0.zip"

    def test_getprojectnames(self, extdb):
        extdb.url2response["https://pypi.python.org/simple/proj1/"] = dict(
            status_code=200, text='''
                <a href="../../pkg/proj1-1.0.zip#md5=123" /> ''')
        extdb.url2response["https://pypi.python.org/simple/proj2/"] = dict(
            status_code=200, text='''
                <a href="../../pkg/proj2-1.0.zip#md5=123" /> ''')
        extdb.url2response["https://pypi.python.org/simple/proj3/"] = dict(
            status_code=404)
        assert len(extdb.getreleaselinks("proj1")) == 1
        assert len(extdb.getreleaselinks("proj2")) == 1
        assert extdb.getreleaselinks("proj3") == 404
        names = extdb.getprojectnames()
        assert names == ["proj1", "proj2"]


def raising():
    raise ValueError(42)

class TestRefreshManager:

    @pytest.fixture
    def refreshmanager(self, request, extdb, xom):
        rf = RefreshManager(extdb, xom)
        #request.addfinalizer(xom.kill_spawned)
        return rf

    def test_pypichanges_nochanges(self, extdb, refreshmanager):
        refreshmanager.redis.delete(refreshmanager.PYPISERIAL, 10)
        proxy = mock.create_autospec(XMLProxy)
        proxy.changelog_last_serial.return_value = 10
        proxy.changelog_since_serial.return_value = []
        with pytest.raises(ValueError):
            refreshmanager.spawned_pypichanges(proxy, proxysleep=raising)
        proxy.changelog_last_serial.assert_called_once_with()
        val = refreshmanager.redis.get(refreshmanager.PYPISERIAL)
        assert int(val) == 10

    def test_pypichanges_changes(self, extdb, refreshmanager, monkeypatch):
        refreshmanager.redis.set(refreshmanager.PYPISERIAL, 10)
        monkeypatch.setattr(extdb.htmlcache, "get", lambda *x,**y: raising())
        pytest.raises(ValueError, lambda: extdb.getreleaselinks("pytest"))
        proxy = mock.create_autospec(XMLProxy)
        proxy.changelog_since_serial.return_value = [
            ["pylib", 11], ["pytest", 12]]
        with pytest.raises(ValueError):
            refreshmanager.spawned_pypichanges(proxy, proxysleep=raising)
        assert not proxy.changelog_last_serial.called
        val = refreshmanager.redis.get(refreshmanager.PYPISERIAL)
        assert int(val) == 12
        invalid = refreshmanager.redis.smembers(refreshmanager.INVALIDSET)
        assert invalid == set(["pytest"])

    def test_refreshprojects(self, redis, extdb, refreshmanager, monkeypatch):
        redis.sadd(refreshmanager.INVALIDSET, "pytest")
        m = mock.Mock()
        monkeypatch.setattr(extdb, "getreleaselinks", m)
        with pytest.raises(ValueError):
            refreshmanager.spawned_refreshprojects(invalidationsleep=raising)
        m.assert_called_once_with("pytest", refresh=True)
        assert not redis.smembers(refreshmanager.INVALIDSET)


def test_requests_httpget_negative_status_code(xom, monkeypatch):
    import requests.exceptions
    def r(*a, **k):
        raise requests.exceptions.RequestException()

    monkeypatch.setattr(xom._httpsession, "get", r)
    r = xom.httpget("http://notexists.qwe", allow_redirects=False)
    assert r.status_code == -1

