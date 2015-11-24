from __future__ import unicode_literals
import time
import hashlib
import pytest
import py

from devpi_server.extpypi import PyPIMirror, PyPIStage
from devpi_server.extpypi import URL, PyPISimpleProxy
from devpi_server.extpypi import parse_index, threadlog
from devpi_server.main import Fatal
from test_devpi_server.conftest import getmd5


class TestIndexParsing:
    simplepy = URL("http://pypi.python.org/simple/py/")

    @pytest.mark.parametrize("hash_type,hash_value", [
        ("sha256", "090123"),
        ("sha224", "1209380123"),
        ("md5", "102938")
    ])
    def test_parse_index_simple_hash_types(self, hash_type, hash_value):
        result = parse_index(self.simplepy,
            """<a href="../../pkg/py-1.4.12.zip#%s=%s" /a>"""
            %(hash_type, hash_value))
        link, = result.releaselinks
        assert link.basename == "py-1.4.12.zip"
        assert link.hash_spec == "%s=%s" %(hash_type, hash_value)
        if hash_type == "md5":
            assert link.md5 == hash_value
        else:
            assert link.md5 is None
        assert link.hash_algo == getattr(hashlib, hash_type)

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

    def test_parse_index_invalid_link(self, pypistage):
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

    def test_parse_index_with_num_in_project(self):
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

    def test_parse_index_with_matchingproject_no_version(self):
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
    def test_parse_project_nomd5(self, pypistage):
        pypistage.mock_simple("pytest", pkgver="pytest-1.0.zip")
        links = pypistage.get_releaselinks("pytest")
        link, = links
        assert link.version == "1.0"
        assert link.entry.url == "https://pypi.python.org/pkg/pytest-1.0.zip"
        assert not link.hash_spec
        assert link.entrypath.endswith("/pytest-1.0.zip")
        assert link.entrypath == link.entry.relpath

    def test_parse_project_replaced_eggfragment(self, pypistage):
        pypistage.mock_simple("pytest", pypiserial=10,
            pkgver="pytest-1.0.zip#egg=pytest-dev1")
        links = pypistage.get_releaselinks("pytest")
        assert links[0].eggfragment == "pytest-dev1"
        pypistage.mock_simple("pytest", pypiserial=11,
            pkgver="pytest-1.0.zip#egg=pytest-dev2")
        threadlog.info("hello")
        links = pypistage.get_releaselinks("pytest")
        assert links[0].eggfragment == "pytest-dev2"

    @pytest.mark.parametrize("hash_type", ["md5", "sha256"])
    def test_parse_project_replaced_md5(self, pypistage, hash_type):
        x = pypistage.mock_simple("pytest", pypiserial=10, hash_type=hash_type,
                                   pkgver="pytest-1.0.zip")
        links = pypistage.get_releaselinks("pytest")
        assert links[0].hash_spec == x.hash_spec

        y = pypistage.mock_simple("pytest", pypiserial=11, hash_type=hash_type,
                                   pkgver="pytest-1.0.zip")
        links = pypistage.get_releaselinks("pytest")
        assert links[0].hash_spec == y.hash_spec
        assert x.hash_spec != y.hash_spec

    def test_get_versiondata_inexistent(self, pypistage):
        pypistage.mock_simple("pytest", status_code=502)
        with pytest.raises(pypistage.UpstreamError):
            pypistage.get_versiondata("Pytest", "1.0")

    def test_get_versiondata(self, pypistage):
        pypistage.mock_simple("pytest", pkgver="pytest-1.0.zip")
        data = pypistage.get_versiondata("Pytest", "1.0")
        assert data["+elinks"]
        assert data["name"] == "pytest"
        assert data["version"] == "1.0"
        assert pypistage.has_project_perstage("pytest")

    def test_get_versiondata_with_egg(self, pypistage):
        pypistage.mock_simple("pytest", text='''
            <a href="../../pkg/tip.zip#egg=pytest-dev" />''')
        data = pypistage.get_versiondata("Pytest", "egg=pytest-dev")
        assert data["+elinks"]

    def test_parse_and_scrape(self, pypistage):
        md5 = getmd5("123")
        pypistage.mock_simple("pytest", text='''
                <a href="../../pkg/pytest-1.0.zip#md5={md5}" />
                <a rel="download" href="https://download.com/index.html" />
            '''.format(md5=md5), pypiserial=20)
        pypistage.url2response["https://download.com/index.html"] = dict(
            status_code=200, text = '''
                <a href="pytest-1.1.tar.gz" /> ''',
            headers = {"content-type": "text/html"})
        links = pypistage.get_releaselinks("pytest")
        assert len(links) == 2
        assert links[0].entry.url == "https://download.com/pytest-1.1.tar.gz"
        assert links[0].entrypath.endswith("/pytest-1.1.tar.gz")

        links = pypistage.get_linkstore_perstage("pytest", "1.0").get_links()
        assert len(links) == 1
        assert links[0].basename == "pytest-1.0.zip"
        assert links[0].entry.hash_spec.startswith("md5=")
        assert links[0].entry.hash_spec.endswith(md5)

        # check refresh
        hashdir_b = getmd5("456")
        pypistage.mock_simple("pytest", text='''
                <a href="../../pkg/pytest-1.0.1.zip#md5={hashdir_b}" />
                <a href="../../pkg/pytest-1.0.zip#md5={md5}" />
                <a rel="download" href="https://download.com/index.html" />
            '''.format(md5=md5, hashdir_b=hashdir_b), pypiserial=25)
        links = pypistage.get_releaselinks("pytest")
        assert len(links) == 3
        assert links[1].entry.url == "https://pypi.python.org/pkg/pytest-1.0.1.zip"
        assert links[1].entrypath.endswith("/pytest-1.0.1.zip")

    def test_parse_and_scrape_non_html_ignored(self, pypistage):
        pypistage.mock_simple("pytest", text='''
                <a href="../../pkg/pytest-1.0.zip#md5={md5}" />
                <a rel="download" href="https://download.com/index.html" />
            ''', pypiserial=20)
        pypistage.url2response["https://download.com/index.html"] = dict(
            status_code=200, text = '''
                <a href="pytest-1.1.tar.gz" /> ''',
            headers = {"content-type": "text/plain"})
        links = pypistage.get_releaselinks("pytest")
        assert len(links) == 1

    def test_get_releaselinks_cache_refresh_on_lower_serial(self, pypistage):
        pypistage.mock_simple("pytest", text='''
                <a href="../../pkg/pytest-1.0.zip#md5={md5}" />
                <a rel="download" href="https://download.com/index.html" />
            ''', pypiserial=10)

        # check get_releaselinks properly returns -2 on stale cache returns
        ret = pypistage.get_releaselinks("pytest")
        assert len(ret) == 1
        pypistage.pypimirror.set_project_serial("pytest", 11)
        with pytest.raises(pypistage.UpstreamError) as excinfo:
            pypistage.get_releaselinks("pytest")
        assert "expected at least 11" in excinfo.value.msg

    def test_get_releaselinks_cache_no_fresh_write(self, pypistage):
        pypistage.mock_simple("pytest", text='''
                <a href="../../pkg/pytest-1.0.zip#md5={md5}" />
                <a rel="download" href="https://download.com/index.html" />
            ''', pypiserial=10)

        ret = pypistage.get_simplelinks("pytest")
        assert len(ret) == 1

        pypistage.keyfs.commit_transaction_in_thread()
        pypistage.keyfs.begin_transaction_in_thread()
        # pretend the last mirror check is very old
        pypistage.xom.set_updated_at(pypistage.name, "pytest", 0)

        # now make sure that we don't cause writes
        commit_serial = pypistage.keyfs.get_current_serial()
        ret2 = pypistage.get_simplelinks("pytest")
        assert ret == ret2
        assert commit_serial == pypistage.keyfs.get_current_serial()

    @pytest.mark.parametrize("errorcode", [404, -1, -2])
    def test_parse_and_scrape_error(self, pypistage, errorcode):
        pypistage.mock_simple("pytest", text='''
                <a href="../../pkg/pytest-1.0.zip#md5={md5}" />
                <a rel="download" href="https://download.com/index.html" />
            ''')
        pypistage.url2response["https://download.com/index.html"] = dict(
            status_code=errorcode, text = 'not found')
        links = pypistage.get_releaselinks("pytest")
        assert len(links) == 1
        assert links[0].entry.url == \
                "https://pypi.python.org/pkg/pytest-1.0.zip"

    def test_scrape_not_recursive(self, pypistage):
        pypistage.mock_simple("pytest", text='''
                <a rel="download" href="https://download.com/index.html" />
            ''')
        md5=getmd5("hello")
        pypistage.url2response["https://download.com/index.html"] = dict(
            status_code=200, text = '''
                <a href="../../pkg/pytest-1.0.zip#md5={md5}" />
                <a rel="download" href="http://whatever.com" />'''.format(
                md5=md5),
            headers = {"content-type": "text/html"},
        )
        pypistage.url2response["https://whatever.com"] = dict(
            status_code=200, text = '<a href="pytest-1.1.zip#md5={md5}" />'
                             .format(md5=md5))
        links = pypistage.get_releaselinks("pytest")
        assert len(links) == 1

    def test_list_projects_perstage(self, pypistage):
        pypistage.mock_simple("proj1", pkgver="proj1-1.0.zip")
        pypistage.mock_simple("proj2", pkgver="proj2-1.0.zip")
        pypistage.url2response["https://pypi.python.org/simple/proj3/"] = dict(
            status_code=404)
        assert len(pypistage.get_releaselinks("proj1")) == 1
        assert len(pypistage.get_releaselinks("proj2")) == 1
        assert not pypistage.has_project_perstage("proj3")
        assert not pypistage.get_releaselinks("proj3")
        assert pypistage.list_projects_perstage() == set(["proj1", "proj2"])

    def test_parse_with_outdated_links_issue165(self, pypistage, caplog):
        pypistage.mock_simple("pytest", pypiserial=10, pkgver="pytest-1.0.zip")
        links = pypistage.get_releaselinks("pytest")
        assert len(links) == 1
        # update the links just as the PyPIMirror thread would
        with pypistage.keyfs.PYPILINKS(project="pytest").update() as cache:
            cache["latest_serial"] = 11
        # make pypi.python.org unreachable
        pypistage.mock_simple("pytest", status_code=-1)
        links2 = pypistage.get_releaselinks("pytest")
        assert links2[0].linkdict == links[0].linkdict and len(links2) == 1
        recs = caplog.getrecords("serving stale.*pytest.*")
        assert len(recs) == 1


@pytest.mark.notransaction
@pytest.mark.xfail(reason="not clear the test is needed now that we normalize ourselves")
def test_pypi_mirror_redirect_to_canonical_issue139(xom, keyfs, mock):
    proxy = mock.create_autospec(PyPISimpleProxy)
    d = {"Hello-World": 10}
    proxy.list_packages_with_serial.return_value = d
    mirror = PyPIMirror(xom)
    mirror.init_pypi_mirror(proxy)
    assert mirror.name2serials == d
    xom.pypimirror = mirror
    pypistage = PyPIStage(xom)
    with keyfs.transaction(write=False):
        # GET http://pypi.python.org/simple/Hello_World
        # will result in the request response to have a "real" URL of
        # http://pypi.python.org/simple/hello-world because of the
        # new pypi normalization code
        pypistage.httpget.mock_simple("hello-world",
                '<a href="Hello_World-1.0.tar.gz" /a>',
                code=200,
                url="http://pypi.python.org/simple/hello-world",)
        rootpypi = xom.model.getstage("root", "pypi")
        l = rootpypi.get_releaselinks("Hello_World")
        assert len(l) == 1


def raise_ValueError():
    raise ValueError(42)

class TestRefreshManager:

    @pytest.mark.notransaction
    def test_init_pypi_mirror(self, xom, keyfs, mock):
        proxy = mock.create_autospec(PyPISimpleProxy)
        d = {"hello": 10, "abc": 42}
        proxy.list_packages_with_serial.return_value = d
        mirror = PyPIMirror(xom)
        mirror.init_pypi_mirror(proxy)
        assert mirror.name2serials == d

    @pytest.mark.notransaction
    def test_pypi_initial(self, makexom, queue, mock):
        proxy = mock.create_autospec(PyPISimpleProxy)
        d = {"hello": 10, "abc": 42}
        proxy.list_packages_with_serial.return_value = d
        class Plugin:
            def devpiserver_pypi_initial(self, stage, name2serials):
                queue.put((stage, name2serials))
        xom = makexom(plugins=[Plugin()])
        xom.pypimirror.init_pypi_mirror(proxy)
        xom.thread_pool.start()
        stage, name2serials = queue.get()
        assert name2serials == d
        for name in name2serials:
            assert py.builtin._istext(name)

    def test_changelog_list_packages_no_network(self, makexom, proxymock):
        proxymock.list_packages_with_serial.return_value = None
        with pytest.raises(Fatal):
            makexom()
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


def test_list_packages_with_serial(reqmock):
    proxy = PyPISimpleProxy()
    reqmock.mockresponse(proxy._simple_url, code=200, data="""
        <html><head><title>Simple Index</title><meta name="api-version" value="2" /></head><body>
            <a href='devpi-server'>devpi-server</a><br/>
            <a href='django'>Django</a><br/>
            <a href='ploy-ansible'>ploy_ansible</a><br/>
        </body></html>""")
    result = proxy.list_packages_with_serial()
    assert result == {'ploy-ansible': -1, 'devpi-server': -1, 'django': -1}


def test_newly_registered_pypi_project(httpget, pypistage):
    assert not pypistage.has_project_perstage("foo")
    # we need to reset the cache time
    pypistage.xom.set_updated_at(pypistage.name, 'foo', 0)
    # now we can check for the new project
    httpget.mock_simple("foo", text='<a href="foo-1.0.tar.gz"</a>')
    assert pypistage.pypimirror.name2serials == {}
    assert pypistage.has_project_perstage("foo")
    #XXX assert pypistage.pypimirror.name2serials == {'foo': -1}


def test_404_on_pypi_cached(httpget, pypistage):
    assert pypistage.xom.get_updated_at(pypistage.name, 'foo') == 0
    assert not pypistage.has_project_perstage("foo")
    assert pypistage.pypimirror.name2serials == {}
    updated_at = pypistage.xom.get_updated_at(pypistage.name, 'foo')
    assert updated_at > 0
    # if we check again, we should get a cached result and no change in the
    # updated_at time
    assert not pypistage.has_project_perstage("foo")
    assert pypistage.pypimirror.name2serials == {}
    assert pypistage.xom.get_updated_at(pypistage.name, 'foo') == updated_at

    pypistage.keyfs.commit_transaction_in_thread()
    pypistage.keyfs.begin_transaction_in_thread()

    # we trigger a fresh check and verify that no new commit takes place
    serial = pypistage.keyfs.get_current_serial()
    pypistage.xom.set_updated_at(pypistage.name, 'foo', 0)
    assert not pypistage.has_project_perstage("foo")
    assert serial == pypistage.keyfs.get_current_serial()
    updated_at = pypistage.xom.get_updated_at(pypistage.name, 'foo')
    assert updated_at > 0

    # make the project exist on pypi, and verify we still get cached result
    httpget.mock_simple("foo", text="", pypiserial=2)
    assert not pypistage.has_project_perstage("foo")
    assert pypistage.pypimirror.name2serials == {}
    assert pypistage.xom.get_updated_at(pypistage.name, 'foo') == updated_at

    # check that no writes were triggered
    pypistage.keyfs.commit_transaction_in_thread()
    pypistage.keyfs.begin_transaction_in_thread()
    assert serial == pypistage.keyfs.get_current_serial()

    # if we reset the cache time, we should get a result
    pypistage.xom.set_updated_at(pypistage.name, 'foo', 0)
    assert pypistage.has_project_perstage("foo")
    time.sleep(0.01)  # to make sure we get a new timestamp
    assert pypistage.pypimirror.name2serials == {'foo': 2}
    assert len(pypistage.get_releaselinks('foo')) == 0
    assert pypistage.xom.get_updated_at(pypistage.name, 'foo') > updated_at

