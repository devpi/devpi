
import pytest
from devpi_server.extpypi import *
import mock

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

    def test_geturl_nofrag(self):
        url = DistURL("http://a/py.tar.gz#egg=py-dev")
        assert url.geturl_nofragment() == "http://a/py.tar.gz"


class TestIndexParsing:
    simplepy = DistURL("http://pypi.python.org/simple/py/")

    def test_parse_index_simple(self):
        result = parse_index(self.simplepy,
            """<a href="../../pkg/py-1.4.12.zip#md5=12ab">qwe</a>""")
        link, = result.releaselinks
        assert link.basename == "py-1.4.12.zip"
        assert link.md5 == "12ab"

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
        assert len(result.crawllinks) == 2
        result.parse_index(DistURL("http://pylib.org"), """
               <a href="http://pylib.org/py-1.1.zip" /a>
               <a href="http://pylib.org/other" rel="download" /a>
        """, scrape=False)
        assert len(result.crawllinks) == 2
        assert len(result.releaselinks) == 2
        links = list(result.releaselinks)
        assert links[0].url == \
                "http://pypi.python.org/pkg/py-1.4.12.zip#md5=12ab"
        assert links[1].url == "http://pylib.org/py-1.1.zip"

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
               <a href="http://pylib.org/py-1.4.12.zip" /a>
               <a href="http://pylib.org/py-1.4.11.zip#md5=1111" /a>
               <a href="http://pylib.org/py-1.4.10.zip#md5=12ab" /a>
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


class TestFSCache:
    #@pytest.mark.parametrize("item", [
    #    "something",
    #    [301, "redirect"],
    #    {"code": 301, "content": "hello"},
    #    404,
    #])
    def test_setbody(self, tmpdir, redis):
        cache = FSCache(tmpdir, redis)
        empty = cache.get("http://whatever/this")
        assert empty is None
        r = cache.setbody("http://whatever/this", "hello")
        assert r.status_code == 200
        assert r.text == "hello"
        assert r.url == "http://whatever/this"

    def test_setmeta(self, tmpdir, redis):
        cache = FSCache(tmpdir, redis)
        r = cache.setmeta("http://whatever/that", status_code=404)
        assert r.status_code == 404
        assert r.text is None
        assert r.url == "http://whatever/that"
        r = cache.setmeta("http://whatever/that", status_code=301,
                          nextlocation="http://whatever/that/this")
        assert r.status_code == 301
        assert r.text is None
        assert r.url == "http://whatever/that"
        assert r.nextlocation == "http://whatever/that/this"



class TestHTTPCacheAdapter:
    @pytest.fixture
    def cache(self, tmpdir, redis):
        return FSCache(tmpdir, redis)

    @pytest.mark.parametrize("target", ["http://hello", "http://hello/"])
    def test_httpcacheget_ok(self, cache, target):
        class httpget:
            def __init__(self, url):
                self.url = url
                self.status_code = 200
                self.text = "hello"
        httpcache = HTTPCacheAdapter(cache, httpget)
        response = httpcache.get(target)
        assert response.status_code == 200
        assert response.text == "hello"
        del httpcache.httpget
        assert httpcache.get(target).text == "hello"

    def test_httpcacheget_redirect_ok(self, cache):
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
        httpcache = HTTPCacheAdapter(cache, httpget)
        text = httpcache.get("http://hello/world").text
        assert text == "redirected"
        del httpcache.httpget  # make sure we don't trigger network anymore
        assert httpcache.get("http://hello/world").text == "redirected"

    def test_httpcacheget_redirect_max(self, cache):
        class httpget:
            def __init__(self, url):
                self.url = url
                self.headers = {"location": "/redirect"}
                self.status_code = 301
        httpcache = HTTPCacheAdapter(cache, httpget)
        assert httpcache.get("http://whatever") == 301

class TestExtPYPIDB:
    @pytest.fixture
    def extdb(self, redis, tmpdir):
        redis.flushdb()
        cache = FSCache(tmpdir, redis)
        url2response = {}
        def httpget(url):
            class response:
                def __init__(self, url):
                    self.__dict__.update(url2response.get(url))
                    self.url = url
            return response(url)

        httpcache = HTTPCacheAdapter(cache, httpget)
        extdb = ExtDB("https://pypi.python.org/", httpcache)
        extdb.url2response = url2response
        return extdb

    def test_parse_project_nomd5(self, extdb):
        extdb.url2response["https://pypi.python.org/simple/pytest/"] = dict(
            status_code=200,
            text='<a href="../../pkg/pytest-1.0.zip#md5=123" />')
        links = extdb.getreleaselinks("pytest")
        link, = links
        assert link.url == "https://pypi.python.org/pkg/pytest-1.0.zip#md5=123"
        assert link.md5 == "123"

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
        assert links[1].url == \
                "https://pypi.python.org/pkg/pytest-1.0.1.zip#md5=456"

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
                "https://pypi.python.org/pkg/pytest-1.0.zip#md5=123"

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
        assert extdb.getreleaselinks("proj3") is None
        names = extdb.getprojectnames()
        assert names == set(["proj1", "proj2"])


def raising():
    raise ValueError(42)

class TestRefreshManager:
    extdb = TestExtPYPIDB.extdb

    @pytest.fixture
    def refreshmanager(self, request, extdb, xom):
        rf = RefreshManager(extdb, xom)
        request.addfinalizer(xom.kill_spawned)
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
        monkeypatch.setattr(extdb.httpcache, "get", lambda *x,**y: raising())
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
