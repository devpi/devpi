import mock
import pytest

from devpi_server.extpypi import *
from devpi_server.main import Fatal, PYPIURL_XMLRPC

class TestIndexParsing:
    simplepy = URL("http://pypi.python.org/simple/py/")

    def test_parse_index_simple(self):
        result = parse_index(self.simplepy,
            """<a href="../../pkg/py-1.4.12.zip#md5=12ab">qwe</a>""")
        link, = result.releaselinks
        assert link.basename == "py-1.4.12.zip"
        assert link.md5 == "12ab"

    def test_parse_index_simple_tilde(self):
        result = parse_index(self.simplepy,
            """<a href="/~user/py-1.4.12.zip#md5=12ab">qwe</a>""")
        link, = result.releaselinks
        assert link.basename == "py-1.4.12.zip"
        assert link.url.endswith("/~user/py-1.4.12.zip#md5=12ab")

    def test_parse_index_simple_nocase(self):
        simplepy = URL("http://pypi.python.org/simple/Py/")
        result = parse_index(simplepy,
            """<a href="../../pkg/py-1.4.12.zip#md5=12ab">qwe</a>
               <a href="../../pkg/PY-1.4.13.zip">qwe</a>
               <a href="../../pkg/pyzip#egg=py-dev">qwe</a>
        """)
        assert len(result.releaselinks) == 3

    def test_parse_index_simple_dir_egg_issue63(self):
        simplepy = URL("http://pypi.python.org/simple/py/")
        result = parse_index(simplepy,
            """<a href="../../pkg/py-1.4.12.zip#md5=12ab">qwe</a>
               <a href="../../pkg/#egg=py-dev">qwe</a>
        """)
        assert len(result.releaselinks) == 1

    def test_parse_index_egg_svnurl(self, monkeypatch):
        # strange case reported by fschulze/witsch where
        # urlparsing will yield a fragment for svn urls.
        # it's not exactly clear how urlparse.uses_fragment
        # sometimes contains "svn" but it's good to check
        # that we are not sensitive to the issue.
        try:
            import urllib.parse as urlparse
        except ImportError:
            # PY2
            import urlparse
        monkeypatch.setattr(urlparse, "uses_fragment",
                            urlparse.uses_fragment + ["svn"])
        simplepy = URL("https://pypi.python.org/simple/zope.sqlalchemy/")
        result = parse_index(simplepy,
            '<a href="svn://svn.zope.org/repos/main/'
            'zope.sqlalchemy/trunk#egg=zope.sqlalchemy-dev" />'
        )
        assert len(result.releaselinks) == 0
        assert len(result.egglinks) == 0
        #assert 0, (result.releaselinks, result.egglinks)

    def test_parse_index_normalized_name(self):
        simplepy = URL("http://pypi.python.org/simple/ndg-httpsclient/")
        result = parse_index(simplepy, """
               <a href="../../pkg/ndg_httpsclient-1.0.tar.gz" />
        """)
        assert len(result.releaselinks) == 1
        assert result.releaselinks[0].url.endswith("ndg_httpsclient-1.0.tar.gz")

    def test_parse_index_two_eggs_same_url(self):
        simplepy = URL("http://pypi.python.org/simple/Py/")
        result = parse_index(simplepy,
            """<a href="../../pkg/pyzip#egg=py-dev">qwe2</a>
               <a href="../../pkg/pyzip#egg=py-dev">qwe</a>
        """)
        assert len(result.releaselinks) == 1

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

    def test_parse_index_invalid_link(self, extdb):
        result = parse_index(self.simplepy, '''
                <a rel="download" href="http:/host.com/123" />
        ''')
        assert result.crawllinks

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

    def test_parse_index_with_wheel(self):
        result = parse_index(self.simplepy,
            """<a href="pkg/py-1.0-cp27-none-linux_x86_64.whl" />
        """)
        assert len(result.releaselinks) == 1
        link, = result.releaselinks
        assert link.basename == "py-1.0-cp27-none-linux_x86_64.whl"

    @pytest.mark.parametrize("basename", [
        "py-1.3.1.tar.gz",
        "py-1.3.1-1.fc12.src.rpm",
        "py-docs-1.0.zip",
        "py-1.1.0.win-amd64.exe",
        "py.tar.gz",
        "py-0.8.msi",
        "py-0.10.0.dmg",
        "py-0.8.deb",
        "py-12.0.0.win32-py2.7.msi",
        "py-1.3.1-1.0rc4.tar.gz", "py-1.0.1.tar.bz2"])
    def test_parse_index_with_valid_basenames(self, basename):
        result = parse_index(self.simplepy, '<a href="pkg/%s" />' % basename)
        assert len(result.releaselinks) == 1
        link, = result.releaselinks
        assert link.basename == basename

    def test_parse_index_with_num_in_projectname(self):
        simple = URL("http://pypi.python.org/simple/py-4chan/")
        result = parse_index(simple, '<a href="pkg/py-4chan-1.0.zip"/>')
        assert len(result.releaselinks) == 1
        assert result.releaselinks[0].basename == "py-4chan-1.0.zip"

    def test_parse_index_unparseable_url(self):
        simple = URL("http://pypi.python.org/simple/x123/")
        result = parse_index(simple, '<a href="http:" />')
        assert len(result.releaselinks) == 0


    def test_parse_index_ftp_ignored_for_now(self):
        result = parse_index(self.simplepy,
            """<a href="http://bb.org/download/py-1.0.zip" />
               <a href="ftp://bb.org/download/py-1.0.tar.gz" />
               <a rel="download" href="ftp://bb.org/download/py-1.1.tar.gz" />
        """)
        assert len(result.releaselinks) == 1
        link, = result.releaselinks
        assert link.basename == "py-1.0.zip"

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

    def test_parse_index_with_matchingprojectname_no_version(self):
        result = parse_index(self.simplepy,
            """<a href="http://bb.org/download/p.zip" />
            <a href="http://bb.org/download/py-1.0.zip" />""")
        assert len(result.releaselinks) == 1

    def test_parse_index_with_non_parseable_hrefs(self):
        result = parse_index(self.simplepy,
            """<a href="qlkwje 1lk23j123123" />
            <a href="http://bb.org/download/py-1.0.zip" />""")
        assert len(result.releaselinks) == 1

    def test_releasefile_and_scrape(self):
        result = parse_index(self.simplepy,
            """<a href="../../pkg/py-1.4.12.zip#md5=12ab">qwe</a>
               <a href="http://pylib.org" rel="homepage">whatever</a>
               <a href="http://pylib2.org" rel="download">whatever2</a>
        """)
        assert len(result.releaselinks) == 1
        assert len(result.crawllinks) == 2
        result.parse_index(URL("http://pylib.org"), """
               <a href="http://pylib.org/py-1.1-py27.egg" />
               <a href="http://pylib.org/other" rel="download" />
        """, scrape=False)
        assert len(result.crawllinks) == 2
        assert len(result.releaselinks) == 2
        links = list(result.releaselinks)
        assert links[0].url == \
                "http://pypi.python.org/pkg/py-1.4.12.zip#md5=12ab"
        assert links[1].url == "http://pylib.org/py-1.1-py27.egg"

    def test_releasefile_and_scrape_no_ftp(self):
        result = parse_index(self.simplepy,
            """<a href="ftp://pylib2.org/py-1.0.tar.gz"
                  rel="download">whatever2</a> """)
        assert len(result.releaselinks) == 0
        assert len(result.crawllinks) == 0


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
        result.parse_index(URL("http://pylib.org"), """
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

class TestExtPYPIDB:
    def test_parse_project_nomd5(self, extdb):
        extdb.setextsimple("pytest", text='''
            <a href="../../pkg/pytest-1.0.zip#md5=123" />''')
        links = extdb.getreleaselinks("pytest")
        link, = links
        assert link.url == "https://pypi.python.org/pkg/pytest-1.0.zip"
        assert link.md5 == "123"
        assert link.relpath.endswith("/pytest-1.0.zip")

    def test_parse_project_replaced_eggfragment(self, extdb):
        extdb.setextsimple("pytest", pypiserial=10, text='''
            <a href="../../pkg/pytest-1.0.zip#egg=pytest-dev1" />''',)
        links = extdb.getreleaselinks("pytest", refresh=10)
        assert links[0].eggfragment == "pytest-dev1"
        extdb.setextsimple("pytest", pypiserial=11, text='''
            <a href="../../pkg/pytest-1.0.zip#egg=pytest-dev2" />''')
        links = extdb.getreleaselinks("pytest", refresh=11)
        assert links[0].eggfragment == "pytest-dev2"

    def test_parse_project_replaced_md5(self, extdb):
        extdb.setextsimple("pytest", pypiserial=10, text='''
            <a href="../../pkg/pytest-1.0.zip#md5=123" />''',)
        links = extdb.getreleaselinks("pytest", refresh=10)
        assert links[0].md5 == "123"
        extdb.setextsimple("pytest", pypiserial=11, text='''
            <a href="../../pkg/pytest-1.0.zip#md5=456" />''')
        links = extdb.getreleaselinks("pytest", refresh=11)
        assert links[0].md5 == "456"


    def test_getprojectconfig(self, extdb):
        extdb.setextsimple("Pytest", text='''
            <a href="../../pkg/pytest-1.0.zip#md5=123" />''')
        config = extdb.get_projectconfig("Pytest")
        data = config["1.0"]
        assert data["+files"]
        assert data["name"] == "Pytest"
        assert data["version"] == "1.0"
        assert extdb.get_project_info("pytest").name == "Pytest"

    def test_getdescription(self, extdb):
        extdb.setextsimple("pytest", text='''
            <a href="../../pkg/pytest-1.0.zip#md5=123" />''')
        content = extdb.get_description("pytest", "1.0")
        assert "refer" in content
        assert "https://pypi.python.org/pypi/pytest/1.0/" in content

    def test_getprojectconfig_with_egg(self, extdb):
        extdb.setextsimple("pytest", text='''
            <a href="../../pkg/tip.zip#egg=pytest-dev" />''')
        config = extdb.get_projectconfig("pytest")
        data = config["egg=pytest-dev"]
        assert data["+files"]

    def test_parse_and_scrape(self, extdb):
        extdb.setextsimple("pytest", text='''
                <a href="../../pkg/pytest-1.0.zip#md5=123" />
                <a rel="download" href="https://download.com/index.html" />
            ''', pypiserial=20)
        extdb.url2response["https://download.com/index.html"] = dict(
            status_code=200, text = '''
                <a href="pytest-1.1.tar.gz" /> ''',
            headers = {"content-type": "text/html"})
        links = extdb.getreleaselinks("pytest")
        assert len(links) == 2
        assert links[0].url == "https://download.com/pytest-1.1.tar.gz"
        assert links[0].relpath.endswith("/pytest-1.1.tar.gz")

        # check refresh
        extdb.setextsimple("pytest", text='''
                <a href="../../pkg/pytest-1.0.1.zip#md5=456" />
                <a href="../../pkg/pytest-1.0.zip#md5=123" />
                <a rel="download" href="https://download.com/index.html" />
            ''', pypiserial=25)
        assert len(extdb.getreleaselinks("pytest")) == 2  # no refresh
        links = extdb.getreleaselinks("pytest", refresh=25)
        assert len(links) == 3
        assert links[1].url == "https://pypi.python.org/pkg/pytest-1.0.1.zip"
        assert links[1].relpath.endswith("/pytest-1.0.1.zip")

    def test_parse_and_scrape_non_html_ignored(self, extdb):
        extdb.setextsimple("pytest", text='''
                <a href="../../pkg/pytest-1.0.zip#md5=123" />
                <a rel="download" href="https://download.com/index.html" />
            ''', pypiserial=20)
        extdb.url2response["https://download.com/index.html"] = dict(
            status_code=200, text = '''
                <a href="pytest-1.1.tar.gz" /> ''',
            headers = {"content-type": "text/plain"})
        links = extdb.getreleaselinks("pytest")
        assert len(links) == 1

    def test_getreleaselinks_cache_refresh_semantics(self, extdb):
        extdb.setextsimple("pytest", text='''
                <a href="../../pkg/pytest-1.0.zip#md5=123" />
                <a rel="download" href="https://download.com/index.html" />
            ''', pypiserial=10)

        # check getreleaselinks properly returns -2 on stale cache returns
        ret = extdb.getreleaselinks("pytest", refresh=11)
        assert ret == -2
        ret = extdb.getreleaselinks("pytest", refresh=10)
        assert len(ret) == 1

        # disable httpget and see if we still get releaselinks for lower
        # refresh serials
        extdb.httpget = None
        ret = extdb.getreleaselinks("pytest", refresh=9)
        assert len(ret) == 1


    @pytest.mark.parametrize("errorcode", [404, -1, -2])
    def test_parse_and_scrape_error(self, extdb, errorcode):
        extdb.setextsimple("pytest", text='''
                <a href="../../pkg/pytest-1.0.zip#md5=123" />
                <a rel="download" href="https://download.com/index.html" />
            ''')
        extdb.url2response["https://download.com/index.html"] = dict(
            status_code=errorcode, text = 'not found')
        links = extdb.getreleaselinks("pytest")
        assert len(links) == 1
        assert links[0].url == \
                "https://pypi.python.org/pkg/pytest-1.0.zip"

    def test_scrape_not_recursive(self, extdb):
        extdb.setextsimple("pytest", text='''
                <a rel="download" href="https://download.com/index.html" />
            ''')
        extdb.url2response["https://download.com/index.html"] = dict(
            status_code=200, text = '''
                <a href="../../pkg/pytest-1.0.zip#md5=123" />
                <a rel="download" href="http://whatever.com" />''',
            headers = {"content-type": "text/html"},
        )
        extdb.url2response["https://whatever.com"] = dict(
            status_code=200, text = '<a href="pytest-1.1.zip#md5=123" />')
        links = extdb.getreleaselinks("pytest")
        assert len(links) == 1

    def xxxtest_scrape_redirect_issue6(self, extdb):
        extdb.url2response["http://github/path"] = dict(
            status_code=302, headers=dict(location="/path"), content='''
                <a rel="download" href="https://download.com/index.html" />
            ''')
        extdb.url2response["https://download.com/index.html"] = dict(
            status_code=200, text = '''
                <a href="../../pkg/pytest-1.0.zip#md5=123" />
                <a rel="download" href="http://whatever.com" />'''
        )
        extdb.url2response["https://whatever.com"] = dict(
            status_code=200, text = '<a href="pytest-1.1.zip#md5=123" />')
        links = extdb.getreleaselinks("pytest")
        assert len(links) == 1

    def test_getprojectnames(self, extdb):
        extdb.mock_simple("proj1", text='''
                           <a href="../../pkg/proj1-1.0.zip#md5=123" /> ''')
        extdb.mock_simple("proj2", text='''
                           <a href="../../pkg/proj2-1.0.zip#md5=123" /> ''')
        extdb.url2response["https://pypi.python.org/simple/proj3/"] = dict(
            status_code=404)
        assert len(extdb.getreleaselinks("proj1")) == 1
        assert len(extdb.getreleaselinks("proj2")) == 1
        assert extdb.getreleaselinks("proj3") == 404
        names = extdb.getprojectnames()
        assert names == ["proj1", "proj2"]

    def test_get_existing_with_302(self, extdb):
        extdb.mock_simple("Hello_this")
        extdb.mock_simple("hello-World")
        extdb.mock_simple("s-p")
        assert extdb.get_project_info("hello-this").name == "Hello_this"
        assert extdb.get_project_info("hello_world").name == "hello-World"
        assert extdb.get_project_info("hello-world").name == "hello-World"
        assert extdb.get_project_info("s-p").name == "s-p"
        assert extdb.get_project_info("s_p").name == "s-p"

def raise_ValueError():
    raise ValueError(42)

class TestRefreshManager:

    def test_init_pypi_mirror(self, extdb, keyfs):
        proxy = mock.create_autospec(XMLProxy)
        d = {"hello": 10, "abc": 42}
        proxy.list_packages_with_serial.return_value = d
        extdb.init_pypi_mirror(proxy)
        assert extdb.name2serials == d
        assert keyfs.PYPISERIALS.get() == d
        assert extdb.getprojectnames() == ["abc", "hello"]

    def test_pypichanges_loop(self, extdb, monkeypatch):
        extdb.process_changelog = mock.Mock()
        extdb.process_refreshes = mock.Mock()
        proxy = mock.create_autospec(XMLProxy)
        changelog = [
            ["pylib", "1.4", 12123, 'new release', 11],
            ["pytest", "2.4", 121231, 'new release', 27]
        ]
        proxy.changelog_since_serial.return_value = changelog

        # we need to have one entry in serials
        extdb.mock_simple("pytest", pypiserial=27)
        with pytest.raises(ValueError):
            extdb.spawned_pypichanges(proxy, proxysleep=raise_ValueError)
        extdb.process_changelog.assert_called_once_with(changelog)
        extdb.process_refreshes.assert_called_once()

    def test_pypichanges_changes(self, extdb, keyfs, monkeypatch):
        assert not extdb.name2serials
        extdb.mock_simple("pytest", '<a href="pytest-2.3.tgz"/a>',
                          pypiserial=20)
        extdb.mock_simple("Django", '<a href="Django-1.6.tgz"/a>',
                          pypiserial=11)
        assert len(extdb.name2serials) == 2
        assert len(extdb.getreleaselinks("pytest")) == 1
        assert len(extdb.getreleaselinks("Django")) == 1
        extdb.process_changelog([
            ["Django", "1.4", 12123, 'new release', 25],
            ["pytest", "2.4", 121231, 'new release', 27]
        ])
        assert len(extdb.name2serials) == 2
        assert keyfs.PYPISERIALS.get()["pytest"] == 27
        assert keyfs.PYPISERIALS.get()["Django"] == 25
        extdb.mock_simple("pytest", '<a href="pytest-2.4.tgz"/a>',
                          pypiserial=27)
        extdb.mock_simple("Django", '<a href="Django-1.7.tgz"/a>',
                          pypiserial=25)
        extdb.process_refreshes()
        assert extdb.getreleaselinks("pytest")[0].basename == "pytest-2.4.tgz"
        assert extdb.getreleaselinks("Django")[0].basename == "Django-1.7.tgz"

    def test_changelog_since_serial_nonetwork(self, extdb, caplog, reqmock):
        extdb.mock_simple("pytest", pypiserial=10)
        reqreply = reqmock.mockresponse(PYPIURL_XMLRPC, code=400)
        xmlproxy = XMLProxy(PYPIURL_XMLRPC)
        with pytest.raises(ValueError):
            extdb.spawned_pypichanges(xmlproxy, proxysleep=raise_ValueError)
        with pytest.raises(ValueError):
            extdb.spawned_pypichanges(xmlproxy, proxysleep=raise_ValueError)
        calls = reqreply.requests
        assert len(calls) == 2
        assert xmlrpc.loads(calls[0].body) == ((10,), "changelog_since_serial")
        assert caplog.getrecords(".*changelog_since_serial.*")

    def test_changelog_list_packages_no_network(self, makexom):
        xmlproxy = mock.create_autospec(XMLProxy)
        xmlproxy.list_packages_with_serial.return_value = None
        with pytest.raises(Fatal):
            makexom(proxy=xmlproxy)
        #assert not xom.keyfs.PYPISERIALS.exists()


def test_requests_httpget_negative_status_code(xom_notmocked, monkeypatch):
    import requests.exceptions
    l = []
    def r(*a, **k):
        l.append(1)
        raise requests.exceptions.RequestException()

    monkeypatch.setattr(xom_notmocked._httpsession, "get", r)

def test_requests_httpget_timeout(xom_notmocked, monkeypatch):
    import requests.exceptions
    def httpget(url, **kw):
        assert kw["timeout"] == 1.2
        raise requests.exceptions.Timeout()

    monkeypatch.setattr(xom_notmocked._httpsession, "get", httpget)
    r = xom_notmocked.httpget("http://notexists.qwe", allow_redirects=False,
                              timeout=1.2)
    assert r.status_code == -1

def test_invalidate_on_version_change(tmpdir, caplog):
    from devpi_server.extpypi import invalidate_on_version_change, ExtDB
    p = tmpdir.ensure("something")
    invalidate_on_version_change(tmpdir)
    assert not p.check()
    assert tmpdir.join(".mirrorversion").read() == ExtDB.VERSION
    rec, = caplog.getrecords()
    assert "format change" in rec.msg
