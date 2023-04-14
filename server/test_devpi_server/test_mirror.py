import aiohttp
import requests.exceptions
import time
import hashlib
import pytest

from devpi_server.mirror import URL, parse_index
from devpi_server.mirror import ProjectNamesCache, ProjectUpdateCache
from test_devpi_server.simpypi import getmd5


def getlinks(text):
    from bs4 import BeautifulSoup
    return BeautifulSoup(text, "html.parser").find_all("a")


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
        """)
        assert len(result.releaselinks) == 2

    def test_parse_index_normalized_name(self):
        simplepy = URL("https://pypi.org/simple/ndg-httpsclient/")
        result = parse_index(simplepy, """
               <a href="../../pkg/ndg_httpsclient-1.0.tar.gz" />
        """)
        assert len(result.releaselinks) == 1
        assert result.releaselinks[0].url.endswith("ndg_httpsclient-1.0.tar.gz")

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

    def test_parse_index_invalid_link(self, pypistage):
        result = parse_index(self.simplepy, '''
                <a rel="download" href="https:/host.com/123" />
        ''')
        assert result.releaselinks == []

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

    def test_parse_index_with_yanked(self):
        result = parse_index(
            self.simplepy,
            """<a href="pkg/py-1.0.zip" data-yanked="" />""")
        assert len(result.releaselinks) == 1
        link, = result.releaselinks
        assert link.basename == "py-1.0.zip"
        assert link.yanked == ""

    def test_parse_index_with_yanked_reason(self):
        result = parse_index(
            self.simplepy,
            """<a href="pkg/py-1.0.zip" data-yanked="bad" />""")
        assert len(result.releaselinks) == 1
        link, = result.releaselinks
        assert link.basename == "py-1.0.zip"
        assert link.yanked == "bad"

    def test_parse_index_with_yanked_hash_spec_is_better(self):
        result = parse_index(self.simplepy,
            """<a href="pkg/py-1.0.zip" data-yanked="" />
               <a href="pkg/py-1.0.zip#md5=pony"/>
        """)
        assert len(result.releaselinks) == 1
        link, = result.releaselinks
        assert link.basename == "py-1.0.zip"
        assert link.hash_spec == "md5=pony"
        assert link.yanked is None

    def test_parse_index_with_yanked_first_with_hash_spec_kept(self):
        result = parse_index(self.simplepy,
            """<a href="pkg/py-1.0.zip#md5=pony"/>
               <a href="pkg/py-1.0.zip#md5=pony" data-yanked="" />
        """)
        assert len(result.releaselinks) == 1
        link, = result.releaselinks
        assert link.basename == "py-1.0.zip"
        assert link.hash_spec == "md5=pony"
        assert link.yanked is None

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
        result.parse_index(URL("http://pylib.org"), """
               <a href="http://pylib.org/py-1.1-py27.egg" />
               <a href="http://pylib.org/other" rel="download" />
        """)
        assert len(result.releaselinks) == 2
        links = list(result.releaselinks)
        assert links[0].url == "https://pypi.org/pkg/py-1.4.12.zip#md5=12ab"
        assert links[1].url == "http://pylib.org/py-1.1-py27.egg"

    def test_releasefile_and_scrape_no_ftp(self):
        result = parse_index(self.simplepy,
            """<a href="ftp://pylib2.org/py-1.0.tar.gz"
                  rel="download">whatever2</a> """)
        assert len(result.releaselinks) == 0

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
        result.parse_index(URL("http://pylib.org"), """
               <a href="http://pylib.org/py-1.4.12.zip" />
               <a href="http://pylib.org/py-1.4.11.zip#md5=1111" />
               <a href="http://pylib.org/py-1.4.10.zip#md5=12ab" />
        """)
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
    def test_parse_pep691(self, pypistage):
        pypistage.mock_simple_projects(["devpi"])
        pypistage.xom.httpget.mockresponse(
            URL(pypistage.mirror_url).joinpath("devpi").asdir().url, code=200,
            content_type="application/vnd.pypi.simple.v1+json",
            text="""{
                "meta": {"api-version": "1.0"},
                "name": "devpi",
                "files": [
                    {
                        "filename":"devpi-0.9.tar.gz",
                        "hashes":{
                            "sha256":"b89846ad42cfee0e44934ef77f28ad44e90b7e744041ace91047dd4c7892cc5e"},
                        "requires-python":null,
                        "url":"https://files.pythonhosted.org/packages/40/b6/45e98504eba446c8e97ce946760893072cdf3bf6cdd18c296394a55621f9/devpi-0.9.tar.gz",
                        "yanked":false}]}""")
        (link,) = pypistage.get_releaselinks("devpi")
        assert link.hash_spec == 'sha256=b89846ad42cfee0e44934ef77f28ad44e90b7e744041ace91047dd4c7892cc5e'
        assert link.yanked is None
        assert link.require_python is None

    def test_parse_pep691_data(self, pypistage):
        pypistage.mock_simple_projects(["devpi"])
        pypistage.xom.httpget.mockresponse(
            URL(pypistage.mirror_url).joinpath("devpi").asdir().url, code=200,
            content_type="application/vnd.pypi.simple.v1+json",
            text="""{
                "meta": {"api-version": "1.0"},
                "name": "devpi",
                "files": [
                    {
                        "filename":"devpi-0.9.tar.gz",
                        "hashes":{
                            "sha256":"b89846ad42cfee0e44934ef77f28ad44e90b7e744041ace91047dd4c7892cc5e"},
                        "requires-python": ">=3.6",
                        "url":"https://files.pythonhosted.org/packages/40/b6/45e98504eba446c8e97ce946760893072cdf3bf6cdd18c296394a55621f9/devpi-0.9.tar.gz",
                        "yanked": "brownbag"}]}""")
        links = pypistage.get_releaselinks("devpi")
        link, = links
        assert link.hash_spec == 'sha256=b89846ad42cfee0e44934ef77f28ad44e90b7e744041ace91047dd4c7892cc5e'
        assert link.yanked == "brownbag"
        assert link.require_python == ">=3.6"

    def test_parse_project_nomd5(self, pypistage):
        pypistage.mock_simple("pytest", pkgver="pytest-1.0.zip")
        links = pypistage.get_releaselinks("pytest")
        link, = links
        assert link.version == "1.0"
        assert link.entry.url == "https://pypi.org/pytest/pytest-1.0.zip"
        assert not link.hash_spec
        assert link.entrypath.endswith("/pytest-1.0.zip")
        assert link.entrypath == link.entry.relpath

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
        assert data["name"] == "Pytest"
        assert data["version"] == "1.0"
        assert pypistage.has_project_perstage("pytest")

    def test_parse_with_external_link(self, pypistage):
        md5 = getmd5("123")
        pypistage.mock_simple("pytest", text='''
                <a href="../../pkg/pytest-1.0.zip#md5={md5}" />
                <a rel="download" href="https://download.com/index.html" />
            '''.format(md5=md5), pypiserial=20)
        links = pypistage.get_releaselinks("pytest")
        # the rel="download" link is just ignored,
        # originally it was scraped/crawled
        assert len(links) == 1
        assert links[0].entry.url == "https://pypi.org/pkg/pytest-1.0.zip"
        assert links[0].entrypath.endswith("/pytest-1.0.zip")

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
        assert len(links) == 2
        assert links[0].entry.url == "https://pypi.org/pkg/pytest-1.0.1.zip"
        assert links[0].entrypath.endswith("/pytest-1.0.1.zip")
        assert links[1].entry.url == "https://pypi.org/pkg/pytest-1.0.zip"
        assert links[1].entrypath.endswith("/pytest-1.0.zip")

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
        (link,) = pypistage.get_releaselinks("pytest")
        recs = caplog.getrecords(".*serving stale links.*")
        assert len(recs) >= 1

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

    def test_parse_with_outdated_links_issue165(self, pypistage, caplog):
        pypistage.mock_simple("pytest", pypiserial=10, pkgver="pytest-1.0.zip")
        links = pypistage.get_releaselinks("pytest")
        assert len(links) == 1

        # make pypi.org unreachable
        pypistage.mock_simple("pytest", status_code=-1)
        links2 = pypistage.get_releaselinks("pytest")
        assert links2[0].linkdict == links[0].linkdict and len(links2) == 1
        recs = caplog.getrecords("serving stale.*pytest.*")
        assert len(recs) >= 1

    def test_pypi_mirror_redirect_to_canonical_issue139(self, pypistage):
        # GET https://pypi.org/simple/Hello_World
        # will result in the request response to have a "real" URL of
        # https://pypi.org/simple/hello-world because of the
        # new pypi normalization code
        pypistage.mock_simple_projects(["Hello_World"])
        pypistage.xom.httpget.mock_simple(
            "Hello_World",
            '<a href="Hello_World-1.0.tar.gz" /a>',
            code=200,
            url="https://pypi.org/simple/hello-world/")
        l = pypistage.get_releaselinks("Hello_World")
        assert len(l) == 1

    def test_newly_registered_pypi_project(self, pypistage):
        assert not pypistage.has_project_perstage("foo")
        pypistage.mock_simple("foo", text='<a href="foo-1.0.tar.gz"</a>')
        assert pypistage.has_project_perstage("foo")

    @pytest.mark.notransaction
    def test_requires_python_caching(self, pypistage):
        pypistage.mock_simple("foo", text='<a href="foo-1.0.tar.gz" data-requires-python="&lt;3"></a>')
        with pypistage.keyfs.transaction(write=False):
            (link,) = pypistage.get_releaselinks("foo")
        assert link.require_python == '<3'
        # make sure we get the cached data, if not throw an error
        pypistage.httpget = None
        with pypistage.keyfs.transaction(write=False):
            (link,) = pypistage.get_releaselinks("foo")
        assert link.require_python == '<3'

    @pytest.mark.notransaction
    def test_yanked_caching(self, pypistage):
        pypistage.mock_simple("foo", text='<a href="foo-1.0.tar.gz" data-yanked=""></a>')
        with pypistage.keyfs.transaction(write=False):
            (link,) = pypistage.get_releaselinks("foo")
        assert link.yanked == ""
        # make sure we get the cached data, if not throw an error
        pypistage.httpget = None
        with pypistage.keyfs.transaction(write=False):
            (link,) = pypistage.get_releaselinks("foo")
        assert link.yanked == ""

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

    @pytest.mark.nomocking
    @pytest.mark.notransaction
    def test_offline_yanked(self, mapp, simpypi, testapp, xom):
        mapp.login('root')
        mapp.modify_index("root/pypi", indexconfig=dict(type='mirror', mirror_url=simpypi.simpleurl))
        # turn off offline mode for preparations
        xom.config.args.offline_mode = False
        content = b'13'
        simpypi.add_release('pkg', pkgver='pkg-0.5.zip', yanked="")
        simpypi.add_release('pkg', pkgver='pkg-1.0.zip')
        simpypi.add_file('/pkg/pkg-0.5.zip', content)
        r = testapp.xget(200, '/root/pypi/+simple/pkg/')
        (link0, link1) = getlinks(r.text)
        assert link0.text == 'pkg-1.0.zip'
        assert link0.get('data-yanked') is None
        assert link1.text == 'pkg-0.5.zip'
        assert link1.get('data-yanked') == ""
        testapp.xget(200, link1['href'].replace('../../', '/root/pypi/'))
        # turn on offline mode for test
        xom.config.args.offline_mode = True
        r = testapp.get('/root/pypi/+simple/pkg/')
        (link,) = getlinks(r.text)
        assert link.text == 'pkg-0.5.zip'
        assert link.get('data-yanked') == ""

    @pytest.mark.notransaction
    def test_etag(self, pypistage):
        pypistage.mock_simple(
            "foo", text='<a href="foo-1.0.tar.gz"</a>', etag='"foo"')
        with pypistage.keyfs.transaction(write=False):
            pypistage.get_simplelinks_perstage("foo")
        call = pypistage.xom.httpget.call_log.pop()
        assert 'If-None-Match' not in call['extra_headers']
        assert pypistage.cache_retrieve_times.get_etag("foo") == '"foo"'
        pypistage.cache_retrieve_times.expire("foo", etag='"foo"')
        with pypistage.keyfs.transaction(write=False):
            pypistage.get_simplelinks_perstage("foo")
        call = pypistage.xom.httpget.call_log.pop()
        assert pypistage.cache_retrieve_times.get_etag("foo") == '"foo"'
        assert call['extra_headers']['If-None-Match'] == '"foo"'
        pypistage.mock_simple(
            "foo", text='<a href="foo-1.0.tar.gz"</a>', etag='"bar"')
        # make sure an expired ETag exists
        pypistage.cache_retrieve_times.expire("foo", etag='"foo"')
        with pypistage.keyfs.transaction(write=False):
            pypistage.get_simplelinks_perstage("foo")
        call = pypistage.xom.httpget.call_log.pop()
        assert call['extra_headers']['If-None-Match'] == '"foo"'
        assert pypistage.cache_retrieve_times.get_etag("foo") == '"bar"'

    @pytest.mark.notransaction
    def test_stale_nocache(self, pypistage, testapp):
        pypistage.mock_simple("foo", text='<a href="foo-1.0.tar.gz"</a>')
        r = testapp.xget(200, '/root/pypi/+simple/foo/')
        assert 'Cache-Control' not in r.headers
        assert 'Expires' not in r.headers
        assert 'Pragma' not in r.headers
        pypistage.mock_simple("foo", status_code=502)
        r = testapp.xget(200, '/root/pypi/+simple/foo/')
        assert 'max-age=0' in r.headers['Cache-Control']
        assert 'Expires' in r.headers
        assert r.headers['Pragma'] == 'no-cache'

    @pytest.mark.notransaction
    def test_stale_nocache_inherit(self, mapp, pypistage, testapp):
        api = mapp.create_and_use(indexconfig=dict(bases='root/pypi'))
        pypistage.mock_simple("foo", text='<a href="foo-1.0.tar.gz"</a>')
        r = testapp.xget(200, f'{api.index}/+simple/foo/')
        assert 'Cache-Control' not in r.headers
        assert 'Expires' not in r.headers
        assert 'Pragma' not in r.headers
        pypistage.mock_simple("foo", status_code=502)
        r = testapp.xget(200, f'{api.index}/+simple/foo/')
        assert 'max-age=0' in r.headers['Cache-Control']
        assert 'Expires' in r.headers
        assert r.headers['Pragma'] == 'no-cache'


class TestMirrorStageprojects:
    def test_get_remote_projects(self, pypistage):
        pypistage.xom.httpget.mockresponse(
            pypistage.mirror_url, code=200, text="""
            <html><head><title>Simple Index</title>
            <meta name="api-version" value="2" /></head>
            <body>
                <a href='devpi-server'>devpi-server</a><br/>
                <a href='django'>Django</a><br/>
                <a href='ploy-ansible/'>ploy_ansible</a><br/>
            </body></html>""")
        (projects, etag) = pypistage._get_remote_projects()
        assert projects == {
            "ploy-ansible": "ploy_ansible",
            "devpi-server": "devpi-server",
            "django": "Django"}
        s = pypistage.list_projects_perstage()
        assert s == {
            "ploy-ansible": "ploy_ansible",
            "devpi-server": "devpi-server",
            "django": "Django"}

    def test_get_remote_projects_pep691_json(self, pypistage):
        pypistage.xom.httpget.mockresponse(
            pypistage.mirror_url, code=200,
            content_type="application/vnd.pypi.simple.v1+json",
            text="""{
                "meta": {"api-version": "1.0"},
                "projects": [
                    {"name": "devpi-server"},
                    {"name": "Django"},
                    {"name": "ploy_ansible"}
                ]}""")
        (projects, etag) = pypistage._get_remote_projects()
        assert projects == {
            "ploy-ansible": "ploy_ansible",
            "devpi-server": "devpi-server",
            "django": "Django"}
        s = pypistage.list_projects_perstage()
        assert s == {
            "ploy-ansible": "ploy_ansible",
            "devpi-server": "devpi-server",
            "django": "Django"}

    def test_get_remote_projects_doctype(self, pypistage):
        pypistage.xom.httpget.mockresponse(
            pypistage.mirror_url, code=200, text="""
            <!DOCTYPE html>
            <html><head><title>Simple Index</title>
            <meta name="api-version" value="2" /></head>
            <body>
                <a href='devpi-server'>devpi-server</a><br/>
            </body></html>""")
        (projects, etag) = pypistage._get_remote_projects()
        assert projects == {"devpi-server": "devpi-server"}

    def test_get_remote_projects_etag(self, pypistage):
        orig_etag = '"foo"'
        changed_etag = '"bar"'
        pypistage.xom.httpget.add(
            pypistage.mirror_url, status_code=200, text="""
            <html><head><title>Simple Index</title>
            <meta name="api-version" value="2" /></head>
            <body>
                <a href='devpi-server'>devpi-server</a><br/>
                <a href='django'>Django</a><br/>
                <a href='ploy-ansible/'>ploy_ansible</a><br/>
            </body></html>""", headers={"ETag": orig_etag})
        pypistage.xom.httpget.add(
            pypistage.mirror_url, status_code=304,
            text="", headers={"ETag": orig_etag})
        pypistage.xom.httpget.add(
            pypistage.mirror_url, status_code=200, text="""
            <html><head><title>Simple Index</title>
            <meta name="api-version" value="2" /></head>
            <body>
                <a href='devpi-server'>devpi-server</a><br/>
                <a href='django'>Django</a><br/>
                <a href='ploy/'>ploy</a><br/>
            </body></html>""", headers={"ETag": changed_etag})
        (projects, etag) = pypistage._get_remote_projects()
        pypistage.cache_projectnames.set(projects, etag)
        assert etag == orig_etag
        assert projects == {
            "ploy-ansible": "ploy_ansible",
            "devpi-server": "devpi-server",
            "django": "Django"}
        call = pypistage.xom.httpget.call_log.pop()
        assert 'If-None-Match' not in call['extra_headers']
        (projects, etag) = pypistage._get_remote_projects()
        pypistage.cache_projectnames.set(projects, etag)
        assert etag == orig_etag
        assert projects == {
            "ploy-ansible": "ploy_ansible",
            "devpi-server": "devpi-server",
            "django": "Django"}
        call = pypistage.xom.httpget.call_log.pop()
        assert call['extra_headers']['If-None-Match'] == orig_etag
        (projects, etag) = pypistage._get_remote_projects()
        pypistage.cache_projectnames.set(projects, etag)
        assert etag == changed_etag
        assert projects == {
            "ploy": "ploy",
            "devpi-server": "devpi-server",
            "django": "Django"}
        (call,) = pypistage.xom.httpget.call_log
        assert call['extra_headers']['If-None-Match'] == orig_etag

    def test_no_mirror_access_for_invalid_packages(self, pypistage):
        """Test that a project needs to be in the index for devpi to attempt to
        load it from the upstream server"""

        VALID = {"devpi-server", "devpi-client", "devpi-web"}
        INVALID = {"invalid", "test", "aaa"}

        pypistage.mock_simple_projects(VALID)
        for name in VALID:
            pypistage.mock_simple(name, text="")
        for name in INVALID:
            # setup 500 returns as fail safe
            pypistage.mock_simple(
                name, text="", status_code=500, add_to_projects=False)

        assert set(pypistage.list_projects_perstage()) == VALID
        call = pypistage.xom.httpget.call_log.pop()
        assert call['url'] == pypistage.mirror_url

        for p in VALID:
            pypistage.get_simplelinks_perstage(p)
            call = pypistage.xom.httpget.call_log.pop()
            assert call['url'] == pypistage.mirror_url.joinpath(p).asdir()
        for p in INVALID:
            with pytest.raises(pypistage.UpstreamNotFoundError):
                pypistage.get_simplelinks_perstage(p)
            # make sure there was no http fetch
            assert len(pypistage.xom.httpget.call_log) == 0

    @pytest.mark.notransaction
    def test_single_project_access_updates_projects(self, pypistage):
        pypistage.mock_simple_projects(["Django"])
        with pypistage.keyfs.transaction(write=False):
            assert pypistage.list_projects_perstage() == {"django": "Django"}
        pypistage.mock_simple("proj1", pkgver="proj1-1.0.zip")
        pypistage.mock_simple("proj2", pkgver="proj2-1.0.zip")
        pypistage.url2response["https://pypi.org/simple/proj3/"] = dict(
            status_code=404)
        with pypistage.keyfs.transaction(write=False):
            assert len(pypistage.get_releaselinks("proj1")) == 1
            assert len(pypistage.get_releaselinks("proj2")) == 1
            assert not pypistage.has_project_perstage("proj3")
            assert not pypistage.get_releaselinks("proj3")
        with pypistage.keyfs.transaction(write=False):
            assert pypistage.list_projects_perstage() == {
                "proj1": "proj1", "proj2": "proj2", "django": "Django"}

    def test_name_cache_expiration_updated_when_no_names_changed(self, httpget, pypistage):
        pypistage.xom.httpget.mockresponse(
            pypistage.mirror_url, code=200, text="""
            <body>
                <a href='django'>Django</a><br/>
            </body>""")
        pypistage.ixconfig['mirror_cache_expiry'] = 0
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

    @pytest.mark.notransaction
    def test_simplelinks_timeout(self, pypistage):
        import asyncio
        # release files should be updated in background in case of timeout
        pypistage.timeout = 0.1
        orig_async_httpget = pypistage.async_httpget

        async def sleeping_async_httpget(*args, **kw):
            await asyncio.sleep(0.2)
            return await orig_async_httpget(*args, **kw)

        # first we need some releases in the db
        pypistage.mock_simple("pkg", text='<a href="pkg-1.0.zip"</a>')
        with pypistage.keyfs.transaction(write=False):
            assert [
                (x.project, x.version)
                for x in pypistage.get_releaselinks("pkg")] == [
                    ('pkg', '1.0')]

        # now expire the cache, add a version on the mirror and fetch again with a timeout
        pypistage.cache_retrieve_times.expire("pkg")
        pypistage.mock_simple("pkg", text='<a href="pkg-1.0.zip"</a><a href="pkg-2.0.zip"</a>')
        pypistage.async_httpget = sleeping_async_httpget
        serial = pypistage.keyfs.get_current_serial()
        # we should get stale results
        with pypistage.keyfs.transaction(write=False):
            assert pypistage.cache_retrieve_times.is_expired("pkg", pypistage.cache_expiry)
            assert [
                (x.project, x.version)
                for x in pypistage.get_releaselinks("pkg")] == [
                    ('pkg', '1.0')]
        # now we wait for the new serial to arrive
        pypistage.keyfs.wait_tx_serial(serial + 1)
        # and we should see the new version
        with pypistage.keyfs.transaction(write=False):
            assert not pypistage.cache_retrieve_times.is_expired("pkg", pypistage.cache_expiry)
            assert sorted([
                (x.project, x.version)
                for x in pypistage.get_releaselinks("pkg")]) == sorted([
                    ('pkg', '1.0'), ('pkg', '2.0')])

    @pytest.mark.nomocking
    @pytest.mark.notransaction
    def test_auth_mirror_url_no_hash(self, caplog, mapp, simpypi, testapp):
        import base64
        url = URL(simpypi.simpleurl).replace(username="foo", password="bar").asdir()
        mapp.login('root')
        mapp.modify_index(
            "root/pypi",
            indexconfig=dict(type='mirror', mirror_url=url.url))
        simpypi.add_release("pkg", pkgver="pkg-1.0.zip")
        content = b'13'
        simpypi.add_file('/pkg/pkg-1.0.zip', content)
        assert not simpypi.requests
        with mapp.xom.keyfs.transaction(write=False):
            pypistage = mapp.xom.model.getstage("root/pypi")
            assert pypistage.mirror_url == url
            (link,) = pypistage.get_simplelinks("pkg")
        assert "foo" not in link.href
        assert "bar" not in link.href
        assert "/+e/" in link.href
        ((path, headers), *_) = simpypi.requests
        (kind, data) = headers["Authorization"].split(None, 1)
        assert kind.lower() == "basic"
        assert base64.b64decode(data) == b"foo:bar"
        simpypi.clear_requests()
        assert not simpypi.requests
        r = testapp.xget(200, f"/{link.href}")
        assert r.body == content
        ((path, headers),) = simpypi.requests
        (kind, data) = headers["Authorization"].split(None, 1)
        assert kind.lower() == "basic"
        assert base64.b64decode(data) == b"foo:bar"
        msgs = [x.getMessage() for x in caplog.getrecords()]
        assert not [
            x for x in msgs
            if "foo:bar" in x
            and "mockresponse" not in x
            and "modified index" not in x]
        assert [x for x in msgs if "foo:***" in x]

    @pytest.mark.nomocking
    @pytest.mark.notransaction
    def test_auth_mirror_url_with_hash(self, caplog, mapp, simpypi, testapp):
        import base64
        url = URL(simpypi.simpleurl).replace(username="foo", password="bar").asdir()
        mapp.login('root')
        mapp.modify_index(
            "root/pypi",
            indexconfig=dict(type='mirror', mirror_url=url.url))
        simpypi.add_release("pkg", pkgver="pkg-1.0.zip#sha256=3fdba35f04dc8c462986c992bcf875546257113072a909c162f7e470e581e278")
        content = b'13'
        simpypi.add_file('/pkg/pkg-1.0.zip', content)
        assert not simpypi.requests
        with mapp.xom.keyfs.transaction(write=False):
            pypistage = mapp.xom.model.getstage("root/pypi")
            assert pypistage.mirror_url == url
            (link,) = pypistage.get_simplelinks("pkg")
        assert "foo" not in link.href
        assert "bar" not in link.href
        assert "/+f/" in link.href
        ((path, headers), *_) = simpypi.requests
        (kind, data) = headers["Authorization"].split(None, 1)
        assert kind.lower() == "basic"
        assert base64.b64decode(data) == b"foo:bar"
        simpypi.clear_requests()
        assert not simpypi.requests
        r = testapp.xget(200, f"/{link.href}")
        assert r.body == content
        ((path, headers),) = simpypi.requests
        (kind, data) = headers["Authorization"].split(None, 1)
        assert kind.lower() == "basic"
        assert base64.b64decode(data) == b"foo:bar"
        msgs = [x.getMessage() for x in caplog.getrecords()]
        assert not [
            x for x in msgs
            if "foo:bar" in x
            and "mockresponse" not in x
            and "modified index" not in x]
        assert [x for x in msgs if "foo:***" in x]

    def test_auth_mirror_url_hidden_in_logs(self, caplog, pypistage):
        pypistage.ixconfig["mirror_url"] = "https://foo:bar@example.com/simple/"
        pypistage.get_releaselinks("pkg")
        msgs = [x.getMessage() for x in caplog.getrecords()]
        assert not [x for x in msgs if "foo:bar" in x and "mockresponse" not in x]
        assert [x for x in msgs if "foo:***" in x]

    def test_auth_mirror_url_user_only(self, caplog, pypistage):
        pypistage.ixconfig["mirror_url"] = "https://foo@example.com/simple/"
        pypistage.get_releaselinks("pkg")
        msgs = [x.getMessage() for x in caplog.getrecords()]
        assert [x for x in msgs if "foo@" in x]

    def test_auth_mirror_url_password_only(self, caplog, pypistage):
        pypistage.ixconfig["mirror_url"] = "https://:bar@example.com/simple/"
        pypistage.get_releaselinks("pkg")
        msgs = [x.getMessage() for x in caplog.getrecords()]
        assert not [x for x in msgs if "/:bar" in x and "mockresponse" not in x]
        assert [x for x in msgs if "/:***" in x]

    @pytest.mark.notransaction
    def test_del_singletons(self, pypistage):
        with pypistage.xom.keyfs.transaction(write=True):
            pypistage.has_project_perstage("pkg")
            assert pypistage.name in pypistage.xom._stagecache
            pypistage.delete()
            assert pypistage.name not in pypistage.xom._stagecache


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


@pytest.mark.asyncio
@pytest.mark.nomocking
@pytest.mark.parametrize("exc", [
    OSError,
    aiohttp.ClientError])
async def test_async_httpget_error(exc, xom, monkeypatch):
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def async_httpget(self, url, **kw):
        raise exc()
        yield

    monkeypatch.setattr(aiohttp.ClientSession, "get", async_httpget)
    r = await xom.async_httpget("http://notexists.qwe", allow_redirects=False)
    assert r.status_code == -1


@pytest.mark.asyncio
@pytest.mark.nomocking
@pytest.mark.parametrize("exc", [
    OSError,
    aiohttp.ClientError])
async def test_get_simplelinks_perstage_when_http_error(exc, pypistage, monkeypatch):
    from contextlib import asynccontextmanager
    from devpi_server.model import SimpleLinks

    # to reach the code path in question, we must have cached links
    links = [("key", "href", "req_py", "yanked")]

    def mock_load_cache_links(project):
        return (True, links, 42)

    monkeypatch.setattr(pypistage, "_load_cache_links", mock_load_cache_links)

    @asynccontextmanager
    async def async_httpget(self, url, **kw):
        raise exc()
        yield

    monkeypatch.setattr(aiohttp.ClientSession, "get", async_httpget)

    assert pypistage.get_simplelinks_perstage("def_missing") == SimpleLinks(links)


def test_is_project_cached(pypistage):
    assert not pypistage.is_project_cached("xyz")
    assert not pypistage.has_project("xyz")
    assert not pypistage.is_project_cached("xyz")

    pypistage.mock_simple("abc", text="")
    assert not pypistage.is_project_cached("abc")
    assert pypistage.has_project("abc")
    assert not pypistage.is_project_cached("abc")
    assert pypistage.get_releaselinks("abc") == []
    assert pypistage.is_project_cached("abc")


@pytest.mark.notransaction
def test_404_on_pypi_cached(pypistage):
    # remember current serial to check later
    pypistage.mock_simple_projects([])
    serial = pypistage.keyfs.get_current_serial()
    retrieve_times = pypistage.cache_retrieve_times
    retrieve_times.expire('foo')
    with pypistage.keyfs.transaction(write=False):
        assert not pypistage.has_project_perstage("foo")
        with pytest.raises(pypistage.UpstreamNotFoundError):
            pypistage.get_simplelinks_perstage("foo")
    updated_at = retrieve_times.get_timestamp("foo")
    assert updated_at > 0
    # if we check again, we should get a cached result and no change in the
    # updated_at time
    with pypistage.keyfs.transaction(write=False):
        assert not pypistage.has_project_perstage("foo")
        with pytest.raises(pypistage.UpstreamNotFoundError):
            pypistage.get_simplelinks_perstage("foo")
    assert retrieve_times.get_timestamp('foo') == updated_at

    # we trigger a fresh check
    retrieve_times.expire('foo')
    with pypistage.keyfs.transaction(write=False):
        assert not pypistage.has_project_perstage("foo")
        with pytest.raises(pypistage.UpstreamNotFoundError):
            pypistage.get_simplelinks_perstage("foo")

    # verify that no new commit took place
    assert serial == pypistage.keyfs.get_current_serial()
    updated_at = retrieve_times.get_timestamp('foo')
    assert updated_at > 0

    # make the project exist on pypi, and verify we still get cached result
    pypistage.mock_simple("foo", text="", pypiserial=2, cache_expire=False)
    with pypistage.keyfs.transaction(write=False):
        assert not pypistage.has_project_perstage("foo")
        with pytest.raises(pypistage.UpstreamNotFoundError):
            pypistage.get_simplelinks_perstage("foo")
    assert retrieve_times.get_timestamp('foo') == updated_at

    # check that no writes were triggered
    assert serial == pypistage.keyfs.get_current_serial()

    # if we reset the cache time, we should get a result
    retrieve_times.expire('foo')
    pypistage.cache_projectnames.expire()
    time.sleep(0.01)  # to make sure we get a new timestamp
    with pypistage.keyfs.transaction(write=False):
        assert pypistage.has_project_perstage("foo")
        assert len(pypistage.get_releaselinks('foo')) == 0
    assert retrieve_times.get_timestamp('foo') > updated_at

    # verify that there was a write this time
    assert pypistage.keyfs.get_current_serial() == (serial + 1)


class TestProjectNamesCache:
    @pytest.fixture
    def cache(self):
        return ProjectNamesCache()

    def test_get_set(self, cache):
        assert cache.get() == dict()
        s = {1: 1, 2: 2, 3: 3}
        cache.set(s, '"foo"')
        s[4] = 4
        assert cache.get() == s
        cache.add('Foo')
        assert 'foo' in cache.get()
        cache.discard('foo')
        assert 'foo' not in cache.get()

    def test_is_expired(self, cache, monkeypatch):
        expiry_time = 100
        s = {1: 1, 2: 2, 3: 3}
        assert cache.get_etag() is None
        cache.set(s, '"foo"')
        assert not cache.is_expired(expiry_time)
        t = time.time() + expiry_time + 1
        monkeypatch.setattr("time.time", lambda: t)
        assert cache.is_expired(expiry_time)
        assert cache.get() == s
        assert cache.get_etag() == '"foo"'


def test_ProjectUpdateCache(monkeypatch):
    x = ProjectUpdateCache()
    expiry_time = 30
    assert x.is_expired("x", expiry_time)
    assert x.get_etag("x") is None
    x.refresh("x", '"foo"')
    assert not x.is_expired("x", expiry_time)
    assert x.get_etag("x") == '"foo"'
    t = time.time() + 35
    monkeypatch.setattr("time.time", lambda: t)
    assert x.is_expired("x", expiry_time)
    assert x.get_etag("x") == '"foo"'
    x.refresh("x", '"bar"')
    assert not x.is_expired("x", expiry_time)
    assert x.get_etag("x") == '"bar"'
    x.expire("x")
    assert x.is_expired("x", expiry_time)
    assert x.get_etag("x") is None

    x.refresh("y", None)
    assert x.get_timestamp("y") == t
    assert x.get_etag("y") is None


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


@pytest.mark.notransaction
def test_get_last_project_change_serial_perstage(xom, pypistage):
    pypistage.mock_simple_projects([], cache_expire=False)
    # get_last_project_change_serial_perstage only works with
    # committed transactions
    with xom.keyfs.transaction() as tx:
        first_serial = tx.at_serial
        assert pypistage.list_projects_perstage() == {}
    with xom.keyfs.transaction() as tx:
        # the list_projects_perstage call above triggered a MIRRORNAMESINIT update
        assert tx.at_serial == (first_serial + 1)
        assert pypistage.get_last_project_change_serial_perstage('pkg') == -1
        with pytest.raises(pypistage.UpstreamNotFoundError):
            pypistage.get_simplelinks_perstage('pkg')
    with xom.keyfs.transaction() as tx:
        # no change in db yet
        assert tx.at_serial == (first_serial + 1)
        assert pypistage.get_last_project_change_serial_perstage('pkg') == -1
        pypistage.mock_simple("pkg", pkgver="pkg-1.0.zip")
        (link,) = pypistage.get_simplelinks_perstage('pkg')
        assert link.key == 'pkg-1.0.zip'
    with xom.keyfs.transaction() as tx:
        # the new project has been updated in the db
        assert tx.at_serial == (first_serial + 2)
        assert pypistage.get_last_project_change_serial_perstage('pkg') == (first_serial + 2)
    with xom.keyfs.transaction() as tx:
        # no change in db yet
        assert tx.at_serial == (first_serial + 2)
        pypistage.mock_simple("other", pkgver="other-1.0.zip")
        (link,) = pypistage.get_simplelinks_perstage('other')
        assert link.key == 'other-1.0.zip'
    with xom.keyfs.transaction() as tx:
        # the new project has been updated in the db
        assert tx.at_serial == (first_serial + 3)
        assert pypistage.get_last_project_change_serial_perstage('other') == (first_serial + 3)
        # but the previous project is at the same serial
        assert pypistage.get_last_project_change_serial_perstage('pkg') == (first_serial + 2)
