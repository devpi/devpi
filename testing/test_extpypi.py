
import pytest
from devpi_server.extpypi import *
import mock

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
            """<a href="http://bb.org/download/py.zip#egg=py-dev" /a>
               <a href="http://bb.org/download/py-1.0.zip" /a>""")
        assert len(result.releaselinks) == 2
        link, link2 = result.releaselinks
        assert link.basename == "py.zip"
        assert link.eggfragment == "py-dev"

    def test_releasefile_and_scrape(self):
        result = parse_index(self.simplepy,
            """<a href="../../pkg/py-1.4.12.zip#md5=12ab">qwe</a>
               <a href="http://pylib.org" rel="homepage">whatever</a>
               <a href="http://pylib2.org" rel="download">whatever2</a>
        """)
        assert len(result.releaselinks) == 1
        assert len(result.crawllinks) == 2
        result.parse_index(DistURL("http://pylib.org"), """
               <a href="http://pylib.org/py-1.1.egg" /a>
               <a href="http://pylib.org/other" rel="download" /a>
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
        assert extdb.getreleaselinks("proj3") is None
        names = extdb.getprojectnames()
        assert names == set(["proj1", "proj2"])

class TestReleaseFileStore:

    def test_canonical_path(self, filestore):
        canonical_relpath = filestore.canonical_relpath
        link = DistURL("https://pypi.python.org/pkg/pytest-1.2.zip#md5=123")
        relpath = canonical_relpath(link)
        parts = relpath.split("/")
        assert len(parts[0]) == filestore.HASHDIRLEN
        assert parts[1] == "pytest-1.2.zip"
        link = DistURL("https://pypi.python.org/pkg/pytest-1.2.zip")
        relpath2 = canonical_relpath(link)
        assert relpath2 == relpath
        link = DistURL("https://pypi.python.org/pkg/pytest-1.3.zip")
        relpath3 = canonical_relpath(link)
        assert relpath3 != relpath
        assert relpath3.endswith("/pytest-1.3.zip")

    def test_canonical_path_egg(self, filestore):
        canonical_relpath = filestore.canonical_relpath
        link = DistURL("https://pypi.python.org/master#egg=pytest-dev")
        relpath = canonical_relpath(link)
        parts = relpath.split("/")
        assert len(parts[0]) == filestore.HASHDIRLEN
        assert parts[1] == "pytest-dev"
        link = DistURL("https://pypi.python.org/master#egg=pytest-dev")
        relpath2 = canonical_relpath(link)


    def test_getentry_fromlink_and_maplink(self, filestore):
        link = DistURL("https://pypi.python.org/pkg/pytest-1.2.zip#md5=123")
        relpath = filestore.canonical_relpath(link)
        entry = filestore.getentry_fromlink(link)
        assert entry.relpath == relpath

    def test_maplink(self, filestore):
        link = DistURL("https://pypi.python.org/pkg/pytest-1.2.zip#md5=123")
        entry1 = filestore.maplink(link, refresh=False)
        entry2 = filestore.maplink(link, refresh=False)
        assert entry1 and entry2
        assert entry1 == entry2
        assert entry1.relpath.endswith("/pytest-1.2.zip")
        assert entry1.md5 == "123"

    def test_maplink_egg(self, filestore):
        link = DistURL("https://pypi.python.org/master#egg=pytest-dev")
        entry1 = filestore.maplink(link, refresh=False)
        entry2 = filestore.maplink(link, refresh=False)
        assert entry1 and entry2
        assert entry1 == entry2
        assert entry1.relpath.endswith("/pytest-dev")
        assert not entry1.md5
        assert entry1.url == link.url_nofrag
        assert entry1.eggfragment == "pytest-dev"

    def test_relpathentry(self, filestore):
        link = DistURL("http://pypi.python.org/pkg/pytest-1.3.zip")
        entry = filestore.getentry_fromlink(link)
        assert not entry
        entry.set(dict(url=link.url, md5="1" * 16))
        assert entry
        assert entry.url == link.url
        assert entry.md5 == "1" * 16

        # reget
        entry = filestore.getentry_fromlink(link)
        assert entry
        assert entry.url == link.url
        assert entry.md5 == "1" * 16

    def test_iterfile(self, filestore, httpget):
        link = DistURL("http://pypi.python.org/pkg/pytest-1.4.zip")
        entry = filestore.maplink(link, refresh=False)
        assert not entry.md5
        headers={"content-length": "3",
                 "last-modified": "Thu, 25 Nov 2010 20:00:27 GMT",
                 "content-type": "application/zip"}
        def iter_content(chunksize):
            yield py.builtin.bytes("12")
            yield py.builtin.bytes("3")

        httpget.url2response[link.url] = dict(status_code=200,
                headers=headers, iter_content = iter_content)
        rheaders, riter = filestore.iterfile(entry.relpath,
                                             httpget, chunksize=1)
        assert rheaders["content-length"] == "3"
        assert rheaders["content-type"] == "application/zip"
        assert rheaders["last-modified"] == headers["last-modified"]
        bytes = py.builtin.bytes().join(riter)
        assert bytes == py.builtin.bytes("123")

        # reget entry and check about content
        entry = filestore.getentry_fromlink(link)
        assert entry
        assert entry.md5 == md5(bytes).hexdigest()
        assert entry.headers == headers
        rheaders, riter = filestore.iterfile(entry.relpath, None, chunksize=1)
        assert rheaders == headers
        bytes = py.builtin.bytes().join(riter)
        assert bytes == py.builtin.bytes("123")

    def test_iterfile_eggfragment(self, filestore, httpget):
        link = DistURL("http://pypi.python.org/master#egg=pytest-dev")
        entry = filestore.maplink(link, refresh=False)
        assert entry.eggfragment
        assert entry.url
        headers={"content-length": "3",
                 "last-modified": "Thu, 25 Nov 2010 20:00:27 GMT",
                 "content-type": "application/zip"}
        l = []
        def iter_content(chunksize):
            yield py.builtin.bytes("1234")
            l.append(1)

        httpget.url2response[entry.url] = dict(status_code=200,
                headers=headers, iter_content = iter_content)
        rheaders, riter = filestore.iterfile(entry.relpath, httpget,
                                             chunksize=10)
        assert py.builtin.bytes().join(riter) == py.builtin.bytes("1234")
        assert len(l) == 1
        rheaders, riter = filestore.iterfile(entry.relpath, httpget,
                                             chunksize=10)
        assert py.builtin.bytes().join(riter) == py.builtin.bytes("1234")
        assert len(l) == 2
        # XXX we could allow getting an old version if it exists
        # and a new request errors out
        #httpget.url2response[entry.url] = dict(status_code=500)
        #rheaders, riter = store.iterfile(entry.relpath, httpget, chunksize=10)
        #assert py.builtin.bytes().join(riter) == py.builtin.bytes("1234")


def raising():
    raise ValueError(42)

class TestRefreshManager:

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


def test_requests_httpget_negative_status_code(xom):
    httpget = resource_httpget(xom)
    r = httpget("http://notexists.qwe", allow_redirects=False)
    assert r.status_code == -1
    r = httpget("http://notexists.qwe", allow_redirects=False)
    assert r.status_code == -1

@pytest.mark.xfail(reason="functional redis other than testing redis")
def test_simple_project_egg(extdb, filestore):
    from pyramid.request import Request
    from devpi_server.wsgi import main
    link = DistURL("http://p/master#egg=pytest-dev")
    entry = filestore.maplink(link)
    entry = filestore.getentry(entry.relpath)
    print entry._mapping, entry.relpath
    req = Request.blank("/pkg/%s" % entry.relpath)

    headers={"content-length": "3",
             "last-modified": "Thu, 25 Nov 2010 20:00:27 GMT",
             "content-type": "application/zip"}
    def iter_content(chunksize):
        yield py.builtin.bytes("12")
        yield py.builtin.bytes("3")
    extdb.url2response[entry.url] = dict(status_code=200,
                headers=headers, iter_content=iter_content)
    app = main(None)
    r = req.get_response(app)
    assert 0
