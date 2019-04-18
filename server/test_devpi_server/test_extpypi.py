from __future__ import unicode_literals
import requests.exceptions
import time
import hashlib
import pytest

from devpi_server.extpypi import URL, parse_index, threadlog
from devpi_server.extpypi import ProjectNamesCache, ProjectUpdateCache
from test_devpi_server.conftest import getmd5


def getlinks(text):
    from bs4 import BeautifulSoup
    return BeautifulSoup(text, "html.parser").findAll("a")


class TestIndexParsing:
    simplepy = URL("https://pypi.org/simple/py/")

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
        simplepy = URL("https://pypi.org/simple/Py/")
        result = parse_index(simplepy,
            """<a href="../../pkg/py-1.4.12.zip#md5=12ab">qwe</a>
               <a href="../../pkg/PY-1.4.13.zip">qwe</a>
               <a href="../../pkg/pyzip#egg=py-dev">qwe</a>
        """)
        assert len(result.releaselinks) == 3

    def test_parse_index_simple_dir_egg_issue63(self):
        simplepy = URL("https://pypi.org/simple/py/")
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
        simplepy = URL("https://pypi.org/simple/zope.sqlalchemy/")
        result = parse_index(simplepy,
            '<a href="svn://svn.zope.org/repos/main/'
            'zope.sqlalchemy/trunk#egg=zope.sqlalchemy-dev" />'
        )
        assert len(result.releaselinks) == 0
        assert len(result.egglinks) == 0
        #assert 0, (result.releaselinks, result.egglinks)

    def test_parse_index_normalized_name(self):
        simplepy = URL("https://pypi.org/simple/ndg-httpsclient/")
        result = parse_index(simplepy, """
               <a href="../../pkg/ndg_httpsclient-1.0.tar.gz" />
        """)
        assert len(result.releaselinks) == 1
        assert result.releaselinks[0].url.endswith("ndg_httpsclient-1.0.tar.gz")

    def test_parse_index_two_eggs_same_url(self):
        simplepy = URL("https://pypi.org/simple/Py/")
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
                <a rel="download" href="https:/host.com/123" />
        ''')
        assert result.crawllinks == {
            URL('https://pypi.org/host.com/123')}

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

    def test_parse_index_with_requires_python(self):
        result = parse_index(self.simplepy,
            """<a href="pkg/py-1.0.zip" data-requires-python="&lt;3" />
        """)
        assert len(result.releaselinks) == 1
        link, = result.releaselinks
        assert link.basename == "py-1.0.zip"
        assert link.requires_python == "<3"

    def test_parse_index_with_requires_python_hash_spec_is_better(self):
        result = parse_index(self.simplepy,
            """<a href="pkg/py-1.0.zip" data-requires-python="&lt;3" />
               <a href="pkg/py-1.0.zip#md5=pony"/>
        """)
        assert len(result.releaselinks) == 1
        link, = result.releaselinks
        assert link.basename == "py-1.0.zip"
        assert link.hash_spec == "md5=pony"
        assert link.requires_python is None

    def test_parse_index_with_requires_python_first_with_hash_spec_kept(self):
        result = parse_index(self.simplepy,
            """<a href="pkg/py-1.0.zip#md5=pony"/>
               <a href="pkg/py-1.0.zip#md5=pony" data-requires-python="&lt;3" />
        """)
        assert len(result.releaselinks) == 1
        link, = result.releaselinks
        assert link.basename == "py-1.0.zip"
        assert link.hash_spec == "md5=pony"
        assert link.requires_python is None

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
        simple = URL("https://pypi.org/simple/py-4chan/")
        result = parse_index(simple, '<a href="pkg/py-4chan-1.0.zip"/>')
        assert len(result.releaselinks) == 1
        assert result.releaselinks[0].basename == "py-4chan-1.0.zip"

    def test_parse_index_unparseable_url(self):
        simple = URL("https://pypi.org/simple/x123/")
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
        assert links[0].url == "https://pypi.org/pkg/py-1.4.12.zip#md5=12ab"
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
        assert link1.url == "https://pypi.org/pkg/py-1.4.12.zip#md5=12ab"
        assert link2.url == "http://pylib.org/py-1.4.11.zip#md5=1111"
        assert link3.url == "https://pypi.org/pkg/py-1.4.10.zip#md5=2222"

def test_get_updated(pypistage):
    c = pypistage.cache_retrieve_times
    c2 = pypistage.cache_retrieve_times
    return c == c2

class TestExtPYPIDB:
    def test_parse_project_nomd5(self, pypistage):
        pypistage.mock_simple("pytest", pkgver="pytest-1.0.zip")
        links = pypistage.get_releaselinks("pytest")
        link, = links
        assert link.version == "1.0"
        assert link.entry.url == "https://pypi.org/pytest/pytest-1.0.zip"
        assert not link.hash_spec
        assert link.entrypath.endswith("/pytest-1.0.zip")
        assert link.entrypath == link.entry.relpath

    def test_parse_project_replaced_eggfragment(self, pypistage):
        pypistage.mock_simple("pytest", pypiserial=10,
            pkgver="pytest-1.0.zip#egg=pytest-dev1")
        links = pypistage.get_releaselinks("pytest")
        assert links[0].eggfragment == "pytest-dev1"

        pypistage.cache_retrieve_times.expire("pytest")
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
        assert links[1].entry.url == "https://pypi.org/pkg/pytest-1.0.1.zip"
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

    def test_get_releaselinks_cache_refresh_on_lower_serial(self, pypistage, caplog):
        pypistage.mock_simple("pytest", text='''
                <a href="../../pkg/pytest-1.0.zip#md5={md5}" />
                <a rel="download" href="https://download.com/index.html" />
            ''', pypiserial=10)

        ret = pypistage.get_releaselinks("pytest")
        assert len(ret) == 1
        pypistage.mock_simple("pytest", text="", pypiserial=9)
        assert len(pypistage.get_releaselinks("pytest")) == 1
        recs = caplog.getrecords(".*serving cached links.*")
        assert len(recs) == 1

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
        pypistage.cache_retrieve_times.expire("pytest")

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
                "https://pypi.org/pkg/pytest-1.0.zip"

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

    def test_parse_with_outdated_links_issue165(self, pypistage, caplog):
        pypistage.mock_simple("pytest", pypiserial=10, pkgver="pytest-1.0.zip")
        links = pypistage.get_releaselinks("pytest")
        assert len(links) == 1

        # make pypi.org unreachable
        pypistage.mock_simple("pytest", status_code=-1)
        links2 = pypistage.get_releaselinks("pytest")
        assert links2[0].linkdict == links[0].linkdict and len(links2) == 1
        recs = caplog.getrecords("serving stale.*pytest.*")
        assert len(recs) == 1

    def test_pypi_mirror_redirect_to_canonical_issue139(self, pypistage):
        # GET https://pypi.org/simple/Hello_World
        # will result in the request response to have a "real" URL of
        # https://pypi.org/simple/hello-world because of the
        # new pypi normalization code
        pypistage.httpget.mock_simple("hello-world",
                '<a href="Hello_World-1.0.tar.gz" /a>',
                code=200,
                url="https://pypi.org/simple/hello-world",)
        l = pypistage.get_releaselinks("Hello_World")
        assert len(l) == 1

    def test_newly_registered_pypi_project(self, pypistage):
        assert not pypistage.has_project_perstage("foo")
        pypistage.mock_simple("foo", text='<a href="foo-1.0.tar.gz"</a>')
        assert pypistage.has_project_perstage("foo")

    def test_requires_python_caching(self, pypistage):
        pypistage.mock_simple("foo", text='<a href="foo-1.0.tar.gz" data-requires-python="&lt;3"></a>')
        (link,) = pypistage.get_releaselinks("foo")
        assert link.require_python == '<3'
        # make sure we get the cached data, if not throw an error
        pypistage.httpget = None
        (link,) = pypistage.get_releaselinks("foo")
        assert link.require_python == '<3'

    @pytest.mark.nomocking
    @pytest.mark.notransaction
    def test_offline_requires_python(self, mapp, simpypi, testapp, xom):
        mapp.login('root')
        mapp.modify_index("root/pypi", indexconfig=dict(type='mirror', mirror_url=simpypi.simpleurl))
        # turn off offline mode for preparations
        xom.config.args.offline_mode = False
        content = b'13'
        simpypi.add_release('pkg', pkgver='pkg-0.5.zip', requires_python='<3')
        simpypi.add_release('pkg', pkgver='pkg-1.0.zip')
        simpypi.add_file('/pkg/pkg-0.5.zip', content)
        r = testapp.xget(200, '/root/pypi/+simple/pkg/')
        (link0, link1) = getlinks(r.text)
        assert link0.text == 'pkg-1.0.zip'
        assert link0.get('data-requires-python') is None
        assert link1.text == 'pkg-0.5.zip'
        assert link1.get('data-requires-python') == '<3'
        testapp.xget(200, link1['href'].replace('../../', '/root/pypi/'))
        # turn on offline mode for test
        xom.config.args.offline_mode = True
        r = testapp.get('/root/pypi/+simple/pkg/')
        (link,) = getlinks(r.text)
        assert link.text == 'pkg-0.5.zip'
        assert link.get('data-requires-python') == '<3'


@pytest.mark.nomockprojectsremote
class TestPyPIStageprojects:
    def test_get_remote_projects(self, pypistage):
        pypistage.httpget.mockresponse(pypistage.mirror_url, code=200, text="""
            <html><head><title>Simple Index</title>
            <meta name="api-version" value="2" /></head>
            <body>
                <a href='devpi-server'>devpi-server</a><br/>
                <a href='django'>Django</a><br/>
                <a href='ploy-ansible/'>ploy_ansible</a><br/>
            </body></html>""")
        x = pypistage._get_remote_projects()
        assert x == set(["ploy-ansible", "devpi-server", "django"])
        s = pypistage.list_projects_perstage()
        assert s == set(["ploy-ansible", "devpi-server", "django"])

    def test_single_project_access_updates_projects(self, pypistage):
        pypistage.httpget.mockresponse(pypistage.mirror_url, code=200, text="""
            <body>
                <a href='django'>Django</a><br/>
            </body>""")
        assert pypistage.list_projects_perstage() == set(["django"])
        pypistage.mock_simple("proj1", pkgver="proj1-1.0.zip")
        pypistage.mock_simple("proj2", pkgver="proj2-1.0.zip")
        pypistage.url2response["https://pypi.org/simple/proj3/"] = dict(
            status_code=404)
        assert len(pypistage.get_releaselinks("proj1")) == 1
        assert len(pypistage.get_releaselinks("proj2")) == 1
        assert not pypistage.has_project_perstage("proj3")
        assert not pypistage.get_releaselinks("proj3")
        assert pypistage.list_projects_perstage() == set(["proj1", "proj2", "django"])

    def test_name_cache_expiration_updated_when_no_names_changed(self, httpget, pypistage):
        pypistage.httpget.mockresponse(pypistage.mirror_url, code=200, text="""
            <body>
                <a href='django'>Django</a><br/>
            </body>""")
        pypistage.cache_expiry = 0
        projectnames = pypistage.cache_projectnames
        assert not projectnames.exists()
        pypistage.list_projects_perstage()
        assert projectnames.exists()
        # simulate some time difference
        projectnames._timestamp = projectnames._timestamp - 1
        ts = projectnames._timestamp
        # fetch again
        pypistage.list_projects_perstage()
        # now the timestamp should differ
        assert projectnames._timestamp > ts


def raise_ValueError():
    raise ValueError(42)


@pytest.mark.nomocking
def test_requests_httpget_negative_status_code(xom, monkeypatch):
    l = []
    def r(*a, **k):
        l.append(1)
        raise requests.exceptions.RequestException()

    monkeypatch.setattr(xom._httpsession, "get", r)


@pytest.mark.nomocking
def test_requests_httpget_timeout(xom, monkeypatch):
    def httpget(url, **kw):
        assert kw["timeout"] == 1.2
        raise requests.exceptions.Timeout()

    monkeypatch.setattr(xom._httpsession, "get", httpget)
    r = xom.httpget("http://notexists.qwe", allow_redirects=False,
                              timeout=1.2)
    assert r.status_code == -1


@pytest.mark.nomocking
@pytest.mark.parametrize("exc", [
    OSError,
    requests.exceptions.ConnectionError])
def test_requests_httpget_error(exc, xom, monkeypatch):
    def httpget(url, **kw):
        raise exc()

    monkeypatch.setattr(xom._httpsession, "get", httpget)
    r = xom.httpget("http://notexists.qwe", allow_redirects=False)
    assert r.status_code == -1


def test_is_project_cached(httpget, pypistage):
    assert not pypistage.is_project_cached("xyz")
    assert not pypistage.has_project("xyz")
    assert not pypistage.is_project_cached("xyz")

    httpget.mock_simple("abc", text="")
    assert not pypistage.is_project_cached("abc")
    assert pypistage.has_project("abc")
    assert pypistage.is_project_cached("abc")


def test_404_on_pypi_cached(httpget, pypistage):
    # remember current serial to check later
    serial = pypistage.keyfs.get_current_serial()
    retrieve_times = pypistage.cache_retrieve_times
    retrieve_times.expire('foo')
    assert not pypistage.has_project_perstage("foo")
    updated_at = retrieve_times.get_timestamp("foo")
    assert updated_at > 0
    # if we check again, we should get a cached result and no change in the
    # updated_at time
    assert not pypistage.has_project_perstage("foo")
    assert retrieve_times.get_timestamp('foo') == updated_at

    pypistage.keyfs.commit_transaction_in_thread()
    pypistage.keyfs.begin_transaction_in_thread()

    # we trigger a fresh check
    retrieve_times.expire('foo')
    assert not pypistage.has_project_perstage("foo")

    # verify that no new commit took place
    pypistage.keyfs.commit_transaction_in_thread()
    pypistage.keyfs.begin_transaction_in_thread()
    assert serial == pypistage.keyfs.get_current_serial()
    updated_at = retrieve_times.get_timestamp('foo')
    assert updated_at > 0

    # make the project exist on pypi, and verify we still get cached result
    httpget.mock_simple("foo", text="", pypiserial=2)
    assert not pypistage.has_project_perstage("foo")
    assert retrieve_times.get_timestamp('foo') == updated_at

    # check that no writes were triggered
    pypistage.keyfs.commit_transaction_in_thread()
    pypistage.keyfs.begin_transaction_in_thread()
    assert serial == pypistage.keyfs.get_current_serial()

    # if we reset the cache time, we should get a result
    retrieve_times.expire('foo')
    time.sleep(0.01)  # to make sure we get a new timestamp
    assert pypistage.has_project_perstage("foo")
    assert len(pypistage.get_releaselinks('foo')) == 0
    assert retrieve_times.get_timestamp('foo') > updated_at

    # verify that there was a write this time
    pypistage.keyfs.commit_transaction_in_thread()
    assert pypistage.keyfs.get_current_serial() == (serial + 1)


class TestProjectNamesCache:
    @pytest.fixture
    def cache(self):
        return ProjectNamesCache()

    def test_get_set(self, cache):
        assert cache.get() == set()
        s = set([1,2,3])
        cache.set(s)
        s.add(4)
        assert cache.get() != s
        s2 = cache.get_inplace()
        s2.add(5)
        assert 5 in cache.get()

    def test_is_expired(self, cache, monkeypatch):
        expiry_time = 100
        s = set([1,2,3])
        cache.set(s)
        assert not cache.is_expired(expiry_time)
        t = time.time() + expiry_time + 1
        monkeypatch.setattr("time.time", lambda: t)
        assert cache.is_expired(expiry_time)
        assert cache.get() == s


def test_ProjectUpdateCache(monkeypatch):
    x = ProjectUpdateCache()
    expiry_time = 30
    assert x.is_expired("x", expiry_time)
    x.refresh("x")
    assert not x.is_expired("x", expiry_time)
    t = time.time() + 35
    monkeypatch.setattr("time.time", lambda: t)
    assert x.is_expired("x", expiry_time)
    x.refresh("x")
    assert not x.is_expired("x", expiry_time)
    x.expire("x")
    assert x.is_expired("x", expiry_time)

    x.refresh("y")
    assert x.get_timestamp("y") == t


@pytest.mark.notransaction
@pytest.mark.with_notifier
@pytest.mark.nomocking
def test_redownload_locally_removed_release(mapp, simpypi):
    from devpi_common.url import URL
    mapp.create_and_login_user('mirror')
    indexconfig = dict(
        type="mirror",
        mirror_url=simpypi.simpleurl,
        mirror_cache_expiry=0)
    mapp.create_index("mirror", indexconfig=indexconfig)
    mapp.use("mirror/mirror")
    content = b'14'
    simpypi.add_release('pkg', pkgver='pkg-1.0.zip')
    simpypi.add_file('/pkg/pkg-1.0.zip', content)
    result = mapp.getreleaseslist("pkg")
    file_relpath = '+files' + URL(result[0]).path
    assert len(result) == 1
    r = mapp.downloadrelease(200, result[0])
    assert r == content
    with mapp.xom.keyfs.transaction(write=False) as tx:
        assert tx.conn.io_file_exists(file_relpath)
    # now remove the local copy
    with mapp.xom.keyfs.transaction(write=True) as tx:
        tx.conn.io_file_delete(file_relpath)
    with mapp.xom.keyfs.transaction(write=False) as tx:
        assert not tx.conn.io_file_exists(file_relpath)
    serial = mapp.xom.keyfs.get_current_serial()
    # and download again
    r = mapp.downloadrelease(200, result[0])
    assert r == content
    with mapp.xom.keyfs.transaction(write=False) as tx:
        assert tx.conn.io_file_exists(file_relpath)
    # the serial should not have increased
    assert serial == mapp.xom.keyfs.get_current_serial()
