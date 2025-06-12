from bs4 import BeautifulSoup
from devpi_common.metadata import parse_version
from devpi_server import __version__ as _devpi_server_version
from devpi_web.main import hookimpl
from functools import partial
import pytest
import re


try:
    from test_devpi_server.plugin import make_file_url
except ImportError:
    from test_devpi_server.conftest import make_file_url  # type: ignore[no-redef]


devpi_server_version = parse_version(_devpi_server_version)
pytestmark = [pytest.mark.notransaction]


def compareable_text(text):
    return re.sub(r'\s+', ' ', text.strip())


@pytest.mark.parametrize("input, expected", [
    ((0, 0), []),
    ((1, 0), [0]),
    ((2, 0), [0, 1]),
    ((2, 1), [0, 1]),
    ((3, 0), [0, 1, 2]),
    ((3, 1), [0, 1, 2]),
    ((3, 2), [0, 1, 2]),
    ((4, 0), [0, 1, 2, 3]),
    ((4, 1), [0, 1, 2, 3]),
    ((4, 2), [0, 1, 2, 3]),
    ((4, 3), [0, 1, 2, 3]),
    ((10, 3), [0, 1, 2, 3, 4, 5, 6, None, 9]),
    ((10, 4), [0, 1, 2, 3, 4, 5, 6, 7, None, 9]),
    ((10, 5), [0, None, 2, 3, 4, 5, 6, 7, 8, 9]),
    ((10, 6), [0, None, 3, 4, 5, 6, 7, 8, 9]),
    ((20, 5), [0, None, 2, 3, 4, 5, 6, 7, 8, None, 19]),
    ((4, 4), ValueError),
])
def test_projectnametokenizer(input, expected):
    from devpi_web.views import batch_list
    if isinstance(expected, list):
        assert batch_list(*input) == expected
    else:
        with pytest.raises(expected):
            batch_list(*input)


@pytest.mark.parametrize("input, expected", [
    (0, (0, "bytes")),
    (1000, (1000, "bytes")),
    (1024, (1, "KB")),
    (2047, (1.9990234375, "KB")),
    (1024 * 1024 - 1, (1023.9990234375, "KB")),
    (1024 * 1024, (1, "MB")),
    (1024 * 1024 * 1024, (1, "GB")),
    (1024 * 1024 * 1024 * 1024, (1, "TB")),
    (1024 * 1024 * 1024 * 1024 * 1024, (1024, "TB"))])
def test_sizeof_fmt(input, expected):
    from devpi_web.views import sizeof_fmt
    assert sizeof_fmt(input) == expected


@pytest.mark.parametrize("outside_url, subpath", [
    ('', ''),
    ('http://localhost/devpi', '/devpi')])
def test_not_found_redirect(testapp, outside_url, subpath):
    r = testapp.xget(302, '/+status/?foo=bar', headers={
                     'accept': "text/html",
                     'X-outside-url': outside_url})
    assert r.location == 'http://localhost%s/+status?foo=bar' % subpath


def test_not_found_project_normalization(testapp):
    r = testapp.get("/foo/bar/pkg.foo", follow=False)
    assert r.status_code == 404
    assert 'The following resource could not be found' in r.text


def test_normalize_project_redirect(mapp, testapp):
    api = mapp.create_and_use()
    mapp.upload_file_pypi("pkg.foo-2.6.tgz", b"123", "pkg.foo", "2.6")
    r = testapp.get("%s/pkg.foo" % api.index, follow=False)
    assert r.status_code == 302
    assert r.location.endswith('/pkg-foo')


def test_not_found_on_post(testapp):
    testapp.post('/foo/bar/', {"hello": ""}, code=404)


@pytest.mark.parametrize("url", [
    '/root/pypi/someproject',
    '/root/pypi/someproject/2.6'])
def test_root_pypi_upstream_error(url, mapp, testapp, pypistage):
    pypistage.mock_simple("someproject", status_code=502)
    r = testapp.get(url, accept="text/html")
    assert r.status_code == 502
    content, = r.html.select('#content')
    text = compareable_text(content.text)
    assert text.startswith('Error An error has occurred: 502 Bad Gateway 502 status on GET')
    assert 'https://' in text
    assert '/simple/someproject/' in text


def test_error_html_only(mapp, testapp, monkeypatch):
    def error(self):
        from pyramid.httpexceptions import HTTPBadGateway
        raise HTTPBadGateway()
    monkeypatch.setattr("devpi_server.views.PyPIView.user_list", error)
    r = testapp.get_json("/")
    assert r.status_code == 502
    assert r.content_type != "text/html"
    assert b"502 Bad Gateway" in r.body


def test_refresh_button(pypistage, testapp):
    pypistage.mock_simple("hello", "<html/>")
    r = testapp.xget(200, "/root/pypi/+simple/hello/")
    assert r.html.select('a') == []
    assert r.headers['X-PYPI-LAST-SERIAL'] == '10000'
    r = testapp.xget(200, "/root/pypi/hello/")
    (input_elem,) = r.html.select('form input[name=refresh]')
    assert input_elem.attrs['value'] == 'Refresh'
    pypistage.mock_simple("hello", pkgver="hello-1.0.zip", pypiserial=10001)
    r = testapp.post("/root/pypi/hello/refresh")
    assert r.status_code == 302
    assert r.location.endswith("/root/pypi/hello")
    r = testapp.xget(200, "/root/pypi/+simple/hello/")
    (a_elem,) = r.html.select('a')
    assert a_elem.text == 'hello-1.0.zip'
    assert a_elem['href'].endswith('+e/https_pypi.org_hello/hello-1.0.zip')
    assert r.headers['X-PYPI-LAST-SERIAL'] == '10001'


@pytest.mark.parametrize("url, headers, selector, expected", [
    (
        "http://localhost:80/{stage}",
        {},
        'form h1 a',
        [('devpi', 'http://localhost/')]),
    (
        "http://localhost:80/{stage}",
        {'x-outside-url': 'http://example.com/foo'},
        'form h1 a',
        [('devpi', 'http://example.com/foo/')]),
    (
        "http://localhost:80/{stage}",
        {'host': 'example.com'},
        'form h1 a',
        [('devpi', 'http://example.com/')]),
    (
        "http://localhost:80/{stage}",
        {'host': 'example.com:3141'},
        'form h1 a',
        [('devpi', 'http://example.com:3141/')]),
    (
        "http://localhost:80/{stage}/pkg1/2.6",
        {},
        '.files td:nth-of-type(1) a',
        [('pkg1-2.6.tgz', partial(make_file_url, 'pkg1-2.6.tgz', b'123'))]),
    (
        "http://localhost:80/{stage}/pkg1/2.6",
        {'x-outside-url': 'http://example.com/foo'},
        '.files td:nth-of-type(1) a',
        [('pkg1-2.6.tgz',
          partial(make_file_url, 'pkg1-2.6.tgz', b'123', baseurl='http://example.com/foo/'))]),
    (
        "http://localhost:80/{stage}/pkg1/2.6",
        {'host': 'example.com'},
        '.files td:nth-of-type(1) a',
        [('pkg1-2.6.tgz',
         partial(make_file_url, 'pkg1-2.6.tgz', b'123', baseurl='http://example.com/'))]),
    (
        "http://localhost:80/{stage}/pkg1/2.6",
        {'host': 'example.com:3141'},
        '.files td:nth-of-type(1) a',
        [('pkg1-2.6.tgz',
         partial(make_file_url, 'pkg1-2.6.tgz', b'123', baseurl='http://example.com:3141/'))]),
])
def test_url_rewriting(url, headers, selector, expected, mapp, testapp):
    api = mapp.create_and_use()
    mapp.upload_file_pypi("pkg1-2.6.tgz", b"123", "pkg1", "2.6")
    url = url.format(stage=api.stagename)
    r = testapp.xget(200, url, headers=dict(accept="text/html", **headers))
    links = [
        (compareable_text(x.text), x.attrs.get('href'))
        for x in r.html.select(selector)]
    expected = [
        (t, (u() if callable(u) else u).format(stage=api.stagename))
        for t, u in expected]
    assert links == expected


def test_redirects(mapp, testapp):
    api = mapp.create_and_use()
    mapp.upload_file_pypi("pkg1-2.6.tgz", b"123", "pkg1", "2.6")
    r = testapp.get('http://localhost', follow=False)
    assert r.status_code == 200
    r = testapp.get('http://localhost/', follow=False)
    assert r.status_code == 200
    r = testapp.get('http://localhost/%s' % api.user, follow=False)
    assert r.status_code == 200
    r = testapp.get('http://localhost/%s/' % api.user, follow=False)
    assert r.status_code == 302
    assert r.headers["Location"] == 'http://localhost/%s' % api.user
    r = testapp.get('http://localhost/%s' % api.stagename, follow=False)
    assert r.status_code == 200
    r = testapp.get('http://localhost/%s/' % api.stagename, follow=False)
    assert r.status_code == 302
    assert r.headers["Location"] == 'http://localhost/%s' % api.stagename
    r = testapp.get('http://localhost/%s/pkg1' % api.stagename, follow=False)
    assert r.status_code == 200
    r = testapp.get('http://localhost/%s/pkg1/' % api.stagename, follow=False)
    assert r.status_code == 302
    assert r.headers["Location"] == 'http://localhost/%s/pkg1' % api.stagename
    r = testapp.get('http://localhost/%s/pkg1/2.6' % api.stagename, follow=False)
    assert r.status_code == 200
    r = testapp.get('http://localhost/%s/pkg1/2.6/' % api.stagename, follow=False)
    assert r.status_code == 302
    assert r.headers["Location"] == 'http://localhost/%s/pkg1/2.6' % api.stagename


@pytest.mark.skipif(devpi_server_version < parse_version("6.8.1.dev"), reason="Needs PATH_INFO fix")
def test_redirects_outside_url(mapp, testapp):
    headers = {'X-outside-url': 'http://outside.com/foo', 'Host': 'outside.com'}
    r = testapp.get('/foo', headers=headers, follow=False)
    assert r.status_code == 200
    r = testapp.get('/foo/', headers=headers, follow=False)
    assert r.status_code == 302
    assert r.location == 'http://outside.com/foo'


def test_static_404(testapp):
    from devpi_web import __version__
    r = testapp.xget(404, '/+static-%s/foo.png' % __version__)
    assert [x.text for x in r.html.select('#content p')] == [
        u'The following resource could not be found:',
        u'http://localhost/+static-%s/foo.png' % __version__]


def _getRouteRequestIface(config, name):
    from pyramid.interfaces import IRouteRequest
    return config.registry.getUtility(IRouteRequest, name)


def _getViewCallable(config, request_iface=None, name=''):
    from pyramid.interfaces import IRequest
    from pyramid.interfaces import IView
    from pyramid.interfaces import IViewClassifier
    from zope.interface import Interface
    if request_iface is None:
        request_iface = IRequest
    return config.registry.adapters.lookup(
        (IViewClassifier, request_iface, Interface), IView, name=name,
        default=None)


class TestStatusView:
    @pytest.fixture
    def plugin(self):
        class Plugin:
            @hookimpl
            def devpiweb_get_status_info(self, request):  # noqa: ARG002
                result = self.results.pop()
                if isinstance(result, Exception):
                    raise result
                return result
        return Plugin()

    @pytest.fixture
    def dummyrequest(self, dummyrequest, plugin, pyramidconfig, xom):
        from devpi_web.main import get_pluginmanager
        dummyrequest.registry = pyramidconfig.registry
        dummyrequest.registry['devpi_version_info'] = []
        pm = get_pluginmanager(xom.config, load_entry_points=False)
        pm.register(plugin)
        dummyrequest.registry['devpiweb-pluginmanager'] = pm
        dummyrequest.registry['xom'] = xom
        dummyrequest.accept = 'text/html'
        dummyrequest.route_url = lambda r, **kw: "#"
        dummyrequest.query_docs_html = ''
        dummyrequest.navigation_info = {'path': ''}
        return dummyrequest

    @pytest.fixture
    def statusview(self, dummyrequest, pyramidconfig):
        from devpi_web.macroregistry import macros

        pyramidconfig.include('pyramid_chameleon')
        pyramidconfig.include("devpi_web.macroregistry")
        pyramidconfig.add_static_view('+static', 'devpi_web:static')
        pyramidconfig.add_route("/+status", "/+status")
        pyramidconfig.scan("devpi_web.macros")
        pyramidconfig.scan('devpi_web.views', ignore=lambda n: 'statusview' not in n)
        dummyrequest.macros = macros(dummyrequest)
        dummyrequest.add_static_css = lambda _href: None
        dummyrequest.add_static_script = lambda _src: None
        return _getViewCallable(
            pyramidconfig,
            request_iface=_getRouteRequestIface(pyramidconfig, "/+status"))

    def test_role(self, bs_text, dummyrequest, plugin, statusview, xom):
        from devpi_web.main import status_info
        plugin.results = [[]]
        dummyrequest.status_info = status_info(dummyrequest)
        result = statusview(None, dummyrequest)
        html = BeautifulSoup(result.body, 'html.parser')
        result = {bs_text(x.select('th')): bs_text(x.select('td')) for x in html.select('table.status tr')}
        assert not xom.is_replica()
        assert result['Role'] in ('MASTER', 'PRIMARY')

    # def test_exception(self, dummyrequest, plugin):
    #     from devpi_web.main import status_info
    #     plugin.results = [ValueError("Foo")]
    #     result = status_info(dummyrequest)

    def test_nothing(self, dummyrequest, plugin):
        from devpi_web.main import status_info
        plugin.results = [[]]
        result = status_info(dummyrequest)
        assert result['status'] == 'ok'
        assert result['short_msg'] == 'ok'
        assert result['msgs'] == []

    def test_warn(self, dummyrequest, plugin):
        from devpi_web.main import status_info
        plugin.results = [[dict(status="warn", msg="Foo")]]
        result = status_info(dummyrequest)
        assert result['status'] == 'warn'
        assert result['short_msg'] == 'degraded'
        assert result['msgs'] == [{'status': 'warn', 'msg': 'Foo'}]

    def test_fatal(self, dummyrequest, plugin):
        from devpi_web.main import status_info
        plugin.results = [[dict(status="fatal", msg="Foo")]]
        result = status_info(dummyrequest)
        assert result['status'] == 'fatal'
        assert result['short_msg'] == 'fatal'
        assert result['msgs'] == [{'status': 'fatal', 'msg': 'Foo'}]

    @pytest.mark.parametrize("msgs", [
        [dict(status="warn", msg="Bar"), dict(status="fatal", msg="Foo")],
        [dict(status="fatal", msg="Foo"), dict(status="warn", msg="Bar")]])
    def test_mixed(self, dummyrequest, plugin, msgs):
        from devpi_web.main import status_info
        plugin.results = [msgs]
        result = status_info(dummyrequest)
        assert result['status'] == 'fatal'
        assert result['short_msg'] == 'fatal'
        assert result['msgs'] == msgs

    def test_status_macros_nothing(self, dummyrequest, plugin, statusview):
        from devpi_web.main import status_info
        plugin.results = [[]]
        dummyrequest.status_info = status_info(dummyrequest)
        result = statusview(None, dummyrequest)
        html = BeautifulSoup(result.body, 'html.parser')
        assert html.select('.statusbadge')[0].text.strip() == 'ok'
        assert 'ok' in html.select('.statusbadge')[0].attrs['class']
        assert html.select('#serverstatus') == []

    def test_status_macros_warn(self, dummyrequest, plugin, statusview):
        from devpi_web.main import status_info
        plugin.results = [[dict(status="warn", msg="Foo")]]
        dummyrequest.status_info = status_info(dummyrequest)
        result = statusview(None, dummyrequest)
        html = BeautifulSoup(result.body, 'html.parser')
        assert html.select('.statusbadge')[0].text.strip() == 'degraded'
        assert 'warn' in html.select('.statusbadge')[0].attrs['class']
        assert html.select('#serverstatus') == []

    def test_status_macros_fatal(self, dummyrequest, plugin, statusview):
        from devpi_web.main import status_info
        plugin.results = [[dict(status="fatal", msg="Foo")]]
        dummyrequest.status_info = status_info(dummyrequest)
        result = statusview(None, dummyrequest)
        html = BeautifulSoup(result.body, 'html.parser')
        assert html.select('.statusbadge')[0].text.strip() == 'fatal'
        assert 'fatal' in html.select('.statusbadge')[0].attrs['class']
        assert 'Foo' in html.select('#serverstatus')[0].text

    @pytest.mark.parametrize("msgs", [
        [dict(status="warn", msg="Bar"), dict(status="fatal", msg="Foo")],
        [dict(status="fatal", msg="Foo"), dict(status="warn", msg="Bar")]])
    def test_status_macros_mixed(self, dummyrequest, plugin, statusview, msgs):
        from devpi_web.main import status_info
        plugin.results = [msgs]
        dummyrequest.status_info = status_info(dummyrequest)
        result = statusview(None, dummyrequest)
        html = BeautifulSoup(result.body, 'html.parser')
        assert html.select('.statusbadge')[0].text.strip() == 'fatal'
        assert 'fatal' in html.select('.statusbadge')[0].attrs['class']
        assert 'Bar' not in html.select('#serverstatus')[0].text
        assert 'Foo' in html.select('#serverstatus')[0].text


class TestReplicaStatusView:
    @pytest.fixture
    def dummyrequest(self, dummyrequest, plugin, pyramidconfig, xom):
        from devpi_web.main import get_pluginmanager
        dummyrequest.registry = pyramidconfig.registry
        dummyrequest.registry['devpi_version_info'] = []
        pm = get_pluginmanager(xom.config, load_entry_points=False)
        pm.register(plugin)
        dummyrequest.registry['devpiweb-pluginmanager'] = pm
        dummyrequest.registry['xom'] = xom
        dummyrequest.accept = 'text/html'
        dummyrequest.route_url = lambda r, **kw: "#"
        dummyrequest.query_docs_html = ''
        dummyrequest.navigation_info = {'path': ''}
        return dummyrequest

    @pytest.fixture
    def plugin(self):
        class Plugin:
            @hookimpl
            def devpiweb_get_status_info(self, request):  # noqa: ARG002
                result = self.results.pop()
                if isinstance(result, Exception):
                    raise result
                return result
        return Plugin()

    @pytest.fixture
    def statusview(self, dummyrequest, pyramidconfig):
        from devpi_web.macroregistry import macros

        pyramidconfig.include('pyramid_chameleon')
        pyramidconfig.include("devpi_web.macroregistry")
        pyramidconfig.add_static_view('+static', 'devpi_web:static')
        pyramidconfig.add_route("/+status", "/+status")
        pyramidconfig.scan("devpi_web.macros")
        pyramidconfig.scan('devpi_web.views', ignore=lambda n: 'statusview' not in n)
        dummyrequest.macros = macros(dummyrequest)
        dummyrequest.add_static_css = lambda _href: None
        dummyrequest.add_static_script = lambda _src: None
        return _getViewCallable(
            pyramidconfig,
            request_iface=_getRouteRequestIface(pyramidconfig, "/+status"))

    @pytest.fixture
    def xom(self, makexom):
        import devpi_web.main
        primary_url_arg = (
            "--master-url"
            if devpi_server_version < parse_version("7dev") else
            "--primary-url")
        return makexom(
            [primary_url_arg, "http://localhost"],
            plugins=[(devpi_web.main, None)])

    @pytest.mark.skipif(devpi_server_version < parse_version("6dev"), reason="Needs replica_thread attribute to be set")
    def test_role(self, bs_text, dummyrequest, plugin, statusview, xom):
        from devpi_web.main import status_info
        assert xom.is_replica()
        xom.config.set_primary_uuid("primary-uuid")
        xom.replica_thread.update_primary_serial(42)
        plugin.results = [[]]
        dummyrequest.status_info = status_info(dummyrequest)
        result = statusview(None, dummyrequest)
        html = BeautifulSoup(result.body, 'html.parser')
        result = {bs_text(x.select('th')): x.select('td') for x in html.select('table.status tr')}
        assert bs_text(result['Master URL']) == 'http://localhost'
        assert bs_text(result['Master UUID']) == 'primary-uuid'
        assert bs_text(result['Master serial']).startswith('42 last time changed')
        assert bs_text(result['Role']) == 'REPLICA'
