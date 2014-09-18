# -*- coding: utf-8 -*-
import json
from devpi_common.archive import zip_dict
from devpi_server import __version__ as devpi_server_version
from pkg_resources import parse_version
from time import struct_time
import py
import pytest
import re


devpi_server_version = parse_version(devpi_server_version)
server21_or_newer = devpi_server_version >= parse_version('2.1dev')


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


@pytest.mark.with_notifier
def test_docs_raw_view(mapp, testapp):
    api = mapp.create_and_use()
    content = zip_dict({"index.html": "<html/>"})
    mapp.upload_doc("pkg1.zip", content, "pkg1", "2.6", code=400)
    mapp.set_versiondata({"name": "pkg1", "version": "2.6"})
    mapp.upload_doc("pkg1.zip", content, "pkg1", "2.6", code=200,
                    waithooks=True)
    r = testapp.xget(302, api.index + "/pkg1/2.6/+doc/")
    testapp.xget(200, r.location)
    r = testapp.xget(404, "/blubber/blubb/pkg1/2.6/+doc/index.html")
    content, = r.html.select('#content')
    assert 'The stage blubber/blubb could not be found.' in content.text.strip()
    r = testapp.xget(404, api.index + "/pkg1/2.7/+doc/index.html")
    content, = r.html.select('#content')
    assert 'No documentation available.' in content.text.strip()
    r = testapp.xget(404, api.index + "/pkg1/2.6/+doc/foo.html")
    content, = r.html.select('#content')
    assert 'File foo.html not found in documentation.' in content.text.strip()


@pytest.mark.with_notifier
def test_docs_view(mapp, testapp):
    api = mapp.create_and_use()
    content = zip_dict({"index.html": "<html/>"})
    mapp.upload_doc("pkg1.zip", content, "pkg1", "2.6", code=400)
    mapp.set_versiondata({"name": "pkg1", "version": "2.6"})
    mapp.upload_doc("pkg1.zip", content, "pkg1", "2.6", code=200,
                    waithooks=True)
    r = testapp.xget(302, api.index + "/pkg1/2.6/+d/")
    r = testapp.xget(200, r.location)
    iframe, = r.html.findAll('iframe')
    assert iframe.attrs['src'] == api.index + "/pkg1/2.6/+doc/index.html"
    r = testapp.xget(404, "/blubber/blubb/pkg1/2.6/+d/index.html")
    content, = r.html.select('#content')
    assert 'The stage blubber/blubb could not be found.' in content.text.strip()
    r = testapp.xget(404, api.index + "/pkg1/2.7/+d/index.html")
    content, = r.html.select('#content')
    assert 'No documentation available.' in content.text.strip()
    r = testapp.xget(404, api.index + "/pkg1/2.6/+d/foo.html")
    content, = r.html.select('#content')
    assert 'File foo.html not found in documentation.' in content.text.strip()


@pytest.mark.with_notifier
def test_docs_latest(mapp, testapp):
    api = mapp.create_and_use()
    content = zip_dict({"index.html": "<html><body>2.6</body></html>"})
    mapp.set_versiondata({"name": "pkg1", "version": "2.6"})
    mapp.upload_doc("pkg1.zip", content, "pkg1", "2.6", code=200,
                    waithooks=True)
    r = testapp.xget(200, api.index + "/pkg1/latest/+d/index.html")
    iframe, = r.html.findAll('iframe')
    assert iframe.attrs['src'] == api.index + "/pkg1/latest/+doc/index.html"
    # navigation shows latest registered version
    navigation_links = r.html.select("#navigation a")
    assert navigation_links[3].text == '2.6'
    # the content is from latest docs though
    r = testapp.xget(200, iframe.attrs['src'])
    assert r.text == "<html><body>2.6</body></html>"
    # now we register a newer version, but docs should still be 2.6
    mapp.set_versiondata({"name": "pkg1", "version": "2.7"}, waithooks=True)
    r = testapp.xget(200, api.index + "/pkg1/latest/+d/index.html")
    iframe, = r.html.findAll('iframe')
    assert iframe.attrs['src'] == api.index + "/pkg1/latest/+doc/index.html"
    # navigation shows latest registered version
    navigation_links = r.html.select("#navigation a")
    assert navigation_links[3].text == '2.7'
    # the content is from latest docs though
    r = testapp.xget(200, iframe.attrs['src'])
    assert r.text == "<html><body>2.6</body></html>"
    # now we upload newer docs
    content = zip_dict({"index.html": "<html><body>2.7</body></html>"})
    mapp.upload_doc("pkg1.zip", content, "pkg1", "2.7", code=200,
                    waithooks=True)
    r = testapp.xget(200, api.index + "/pkg1/latest/+d/index.html")
    iframe, = r.html.findAll('iframe')
    assert iframe.attrs['src'] == api.index + "/pkg1/latest/+doc/index.html"
    # navigation shows latest registered version
    navigation_links = r.html.select("#navigation a")
    assert navigation_links[3].text == '2.7'
    # the content is from latest docs though
    r = testapp.xget(200, iframe.attrs['src'])
    assert r.text == "<html><body>2.7</body></html>"


def test_not_found_redirect(testapp):
    r = testapp.get('/root/pypi/?foo=bar', headers=dict(accept="text/html"))
    assert r.status_code == 302
    assert r.location == 'http://localhost/root/pypi?foo=bar'


def test_not_found_on_post(testapp):
    testapp.post('/foo/bar/', {"hello": ""}, code=404)


def test_root_view(testapp):
    r = testapp.get('/', headers=dict(accept="text/html"))
    assert r.status_code == 200
    links = r.html.select('#content a')
    assert [(l.text, l.attrs['href']) for l in links] == [
        ("root/pypi", "http://localhost/root/pypi")]


def test_root_view_with_index(mapp, testapp):
    api = mapp.create_and_use()
    r = testapp.get('/', headers=dict(accept="text/html"))
    assert r.status_code == 200
    links = r.html.select('#content a')
    assert [(l.text, l.attrs['href']) for l in links] == [
        ("root/pypi", "http://localhost/root/pypi"),
        (api.stagename, "http://localhost/%s" % api.stagename)]


def test_index_view_root_pypi(testapp):
    r = testapp.get('/root/pypi', headers=dict(accept="text/html"))
    assert r.status_code == 200
    links = r.html.select('#content a')
    assert [(l.text, l.attrs['href']) for l in links] == [
        ("simple index", "http://localhost/root/pypi/+simple/")]


def test_index_view(mapp, testapp):
    api = mapp.create_and_use()
    r = testapp.get(api.index, headers=dict(accept="text/html"))
    assert r.status_code == 200
    links = r.html.select('#content a')
    assert [(l.text, l.attrs['href']) for l in links] == [
        ("simple index", "http://localhost/%s/+simple/" % api.stagename),
        ("root/pypi", "http://localhost/root/pypi"),
        ("simple", "http://localhost/root/pypi/+simple/")]


def test_index_not_found(testapp):
    r = testapp.get("/blubber/blubb", headers=dict(accept="text/html"))
    assert r.status_code == 404
    content, = r.html.select('#content')
    assert 'The stage blubber/blubb could not be found.' in content.text.strip()


def test_index_view_project_info(mapp, testapp):
    api = mapp.create_and_use()
    mapp.set_versiondata({"name": "pkg1", "version": "2.6"})
    r = testapp.get(api.index, headers=dict(accept="text/html"))
    assert r.status_code == 200
    links = r.html.select('#content a')
    assert [(l.text, l.attrs['href']) for l in links] == [
        ("simple index", "http://localhost/%s/+simple/" % api.stagename),
        ("pkg1-2.6", "http://localhost/%s/pkg1/2.6" % api.stagename),
        ("root/pypi", "http://localhost/root/pypi"),
        ("simple", "http://localhost/root/pypi/+simple/")]


@pytest.mark.with_notifier
def test_index_view_project_files(mapp, testapp):
    api = mapp.create_and_use()
    mapp.upload_file_pypi("pkg1-2.6.tar.gz", b"content", "pkg1", "2.6")
    r = testapp.xget(200, api.index, headers=dict(accept="text/html"))
    links = r.html.select('#content a')
    assert [(l.text, l.attrs['href']) for l in links] == [
        ("simple index", "http://localhost/%s/+simple/" % api.stagename),
        ("pkg1-2.6", "http://localhost/%s/pkg1/2.6" % api.stagename),
        ("pkg1-2.6.tar.gz", "http://localhost/%s/+f/9a0/364b9e99bb480/pkg1-2.6.tar.gz#md5=9a0364b9e99bb480dd25e1f0284c8555" % api.stagename),
        ("root/pypi", "http://localhost/root/pypi"),
        ("simple", "http://localhost/root/pypi/+simple/")]
    mapp.upload_file_pypi(
        "pkg1-2.6.zip", b"contentzip", "pkg1", "2.6")
    r = testapp.get(api.index, headers=dict(accept="text/html"))
    assert r.status_code == 200
    links = r.html.select('#content a')
    assert [(l.text, l.attrs['href']) for l in links] == [
        ("simple index", "http://localhost/%s/+simple/" % api.stagename),
        ("pkg1-2.6", "http://localhost/%s/pkg1/2.6" % api.stagename),
        ("pkg1-2.6.tar.gz", "http://localhost/%s/+f/9a0/364b9e99bb480/pkg1-2.6.tar.gz#md5=9a0364b9e99bb480dd25e1f0284c8555" % api.stagename),
        ("pkg1-2.6.zip", "http://localhost/%s/+f/523/60ae08d733016/pkg1-2.6.zip#md5=52360ae08d733016c5603d54b06b5300" % api.stagename),
        ("root/pypi", "http://localhost/root/pypi"),
        ("simple", "http://localhost/root/pypi/+simple/")]


@pytest.mark.with_notifier
def test_index_view_project_docs(mapp, testapp):
    api = mapp.create_and_use()
    mapp.set_versiondata({"name": "pkg1", "version": "2.6"})
    content = zip_dict({"index.html": "<html/>"})
    mapp.upload_doc("pkg1.zip", content, "pkg1", "2.6", code=200,
                    waithooks=True)
    r = testapp.get(api.index, headers=dict(accept="text/html"))
    assert r.status_code == 200
    links = r.html.select('#content a')
    assert [(l.text, l.attrs['href']) for l in links] == [
        ("simple index", "http://localhost/%s/+simple/" % api.stagename),
        ("pkg1-2.6", "http://localhost/%s/pkg1/2.6" % api.stagename),
        ("pkg1-2.6", "http://localhost/%s/pkg1/2.6/+d/index.html" % api.stagename),
        ("root/pypi", "http://localhost/root/pypi"),
        ("simple", "http://localhost/root/pypi/+simple/")]


def test_index_view_permissions(mapp, testapp):
    api = mapp.create_and_use()
    mapp.set_acl([api.user, ':developers', ':ANONYMOUS:'])
    r = testapp.xget(200, api.index, headers=dict(accept="text/html"))
    elements = r.html.select('#content dl.permissions > *')
    text = [re.sub('\s+', ' ', x.text.strip()) for x in elements]
    assert text == [
        'upload', 'Users: user1', 'Groups: developers', 'Special: ANONYMOUS']


def test_project_view(mapp, testapp):
    api = mapp.create_and_use()
    mapp.upload_file_pypi(
        "pkg1-2.6.tar.gz", b"content", "pkg1", "2.6")
    mapp.upload_file_pypi(
        "pkg1-2.6.zip", b"contentzip", "pkg1", "2.6")
    mapp.upload_file_pypi(
        "pkg1-2.7.tar.gz", b"content", "pkg1", "2.7")
    r = testapp.get(api.index + '/pkg1', headers=dict(accept="text/html"))
    assert r.status_code == 200
    links = r.html.select('#content a')
    assert [(l.text, l.attrs['href']) for l in links] == [
        (api.stagename, "http://localhost/%s" % api.stagename),
        ("2.7", "http://localhost/%s/pkg1/2.7" % api.stagename),
        (api.stagename, "http://localhost/%s" % api.stagename),
        ("2.6", "http://localhost/%s/pkg1/2.6" % api.stagename)]


def test_project_not_found(mapp, testapp):
    api = mapp.create_and_use()
    r = testapp.get("/blubber/blubb/pkg1", headers=dict(accept="text/html"))
    assert r.status_code == 404
    content, = r.html.select('#content')
    assert 'The stage blubber/blubb could not be found.' in content.text.strip()
    r = testapp.get(api.index + "/pkg1", headers=dict(accept="text/html"))
    assert r.status_code == 404
    content, = r.html.select('#content')
    assert 'The project pkg1 does not exist.' in content.text.strip()


def test_project_view_root_pypi(mapp, testapp, pypistage):
    pypistage.mock_simple("pkg1", text='''
            <a href="../../pkg/pkg1-2.7.zip" />
            <a href="../../pkg/pkg1-2.6.zip" />
        ''', pypiserial=10)
    r = testapp.get('/root/pypi/pkg1', headers=dict(accept="text/html"))
    assert r.status_code == 200
    links = r.html.select('#content a')
    assert [(l.text, l.attrs['href']) for l in links] == [
        ("root/pypi", "http://localhost/root/pypi"),
        ("2.7", "http://localhost/root/pypi/pkg1/2.7"),
        ("root/pypi", "http://localhost/root/pypi"),
        ("2.6", "http://localhost/root/pypi/pkg1/2.6")]


@pytest.mark.with_notifier
def test_version_view(mapp, testapp, monkeypatch):
    import devpi_server.model
    # use fixed time
    gmtime = lambda *x: struct_time((2014, 9, 15, 11, 11, 11, 0, 258, 0))
    monkeypatch.setattr('time.gmtime', gmtime)
    monkeypatch.setattr(devpi_server.model, 'gmtime', gmtime, raising=server21_or_newer)
    api = mapp.create_and_use()
    mapp.upload_file_pypi(
        "pkg1-2.6.tar.gz", b"content", "pkg1", "2.6")
    mapp.upload_file_pypi(
        "pkg1-2.6.zip", b"contentzip", "pkg1", "2.6")
    content = zip_dict({"index.html": "<html/>"})
    mapp.upload_doc("pkg1.zip", content, "pkg1", "2.6", code=200)
    mapp.set_versiondata({
        "name": "pkg1",
        "version": "2.6",
        "author": "Foo Bear",
        "description": u"föö".encode('utf-8')},
        waithooks=True)
    r = testapp.get(api.index + '/pkg1/2.6', headers=dict(accept="text/html"))
    assert r.status_code == 200
    assert r.html.find('title').text == "user1/dev/: pkg1-2.6 metadata and description"
    info = dict((t.text for t in x.findAll('td')) for x in r.html.select('.projectinfos tr'))
    assert sorted(info.keys()) == ['author']
    assert info['author'] == 'Foo Bear'
    description = r.html.select('#description')
    assert len(description) == 1
    description = description[0]
    assert py.builtin._totext(
        description.renderContents().strip(),
        'utf-8') == u'<p>föö</p>'
    filesinfo = [
        tuple(
            re.sub('\s+', ' ', t.text.strip()).split()
            for t in x.findAll('td'))
        for x in r.html.select('.files tbody tr')]
    assert [x[:3] + x[-2:] for x in filesinfo] == [
        (['pkg1-2.6.tar.gz', '9a0364b9e99bb480dd25e1f0284c8555'], ['Source'], [], [u'7', u'bytes'], []),
        (['pkg1-2.6.zip', '52360ae08d733016c5603d54b06b5300'], ['Source'], [], [u'10', u'bytes'], [])]
    if server21_or_newer:
        assert [x[3] for x in filesinfo] == [
            [u'Last', u'modified', u'2014-09-15', u'11:11:11',
             u'Uploaded', u'to', u'user1/dev', u'by', u'user1', u'2014-09-15', u'11:11:11'],
            [u'Last', u'modified', u'2014-09-15', u'11:11:11',
             u'Uploaded', u'to', u'user1/dev', u'by', u'user1', u'2014-09-15', u'11:11:11']]
    else:
        assert [x[3] for x in filesinfo] == [
            [u'Last', u'modified', u'2014-09-15', u'11:11:11'],
            [u'Last', u'modified', u'2014-09-15', u'11:11:11']]
    links = r.html.select('#content a')
    if server21_or_newer:
        assert [(l.text.strip(), l.attrs['href']) for l in links] == [
            ("Documentation", "http://localhost/%s/pkg1/2.6/+d/index.html" % api.stagename),
            ("Simple index", "http://localhost/%s/+simple/pkg1" % api.stagename),
            ("pkg1-2.6.tar.gz", "http://localhost/%s/+f/9a0/364b9e99bb480/pkg1-2.6.tar.gz#md5=9a0364b9e99bb480dd25e1f0284c8555" % api.stagename),
            ('user1/dev', 'http://localhost/user1/dev'),
            ("pkg1-2.6.zip", "http://localhost/%s/+f/523/60ae08d733016/pkg1-2.6.zip#md5=52360ae08d733016c5603d54b06b5300" % api.stagename),
            ('user1/dev', 'http://localhost/user1/dev')]
    else:
        assert [(l.text.strip(), l.attrs['href']) for l in links] == [
            ("Documentation", "http://localhost/%s/pkg1/2.6/+d/index.html" % api.stagename),
            ("Simple index", "http://localhost/%s/+simple/pkg1" % api.stagename),
            ("pkg1-2.6.tar.gz", "http://localhost/%s/+f/9a0/364b9e99bb480/pkg1-2.6.tar.gz#md5=9a0364b9e99bb480dd25e1f0284c8555" % api.stagename),
            ("pkg1-2.6.zip", "http://localhost/%s/+f/523/60ae08d733016/pkg1-2.6.zip#md5=52360ae08d733016c5603d54b06b5300" % api.stagename)]


def test_version_not_found(mapp, testapp):
    api = mapp.create_and_use()
    mapp.upload_file_pypi(
        "pkg1-2.6.tar.gz", b"content", "pkg1", "2.6")
    r = testapp.get("/blubber/blubb/pkg1/2.6", headers=dict(accept="text/html"))
    assert r.status_code == 404
    content, = r.html.select('#content')
    assert 'The stage blubber/blubb could not be found.' in content.text.strip()
    r = testapp.get(api.index + "/pkg2/2.6", headers=dict(accept="text/html"))
    assert r.status_code == 404
    content, = r.html.select('#content')
    assert 'The project pkg2 does not exist.' in content.text.strip()
    r = testapp.get(api.index + "/pkg1/2.7", headers=dict(accept="text/html"))
    assert r.status_code == 404
    content, = r.html.select('#content')
    assert 'The version 2.7 of project pkg1 does not exist.' in content.text.strip()


def test_version_view_root_pypi(mapp, testapp, pypistage):
    pypistage.mock_simple("pkg1", text='''
            <a href="../../pkg/pkg1-2.6.zip" />
        ''', pypiserial=10)
    r = testapp.xget(200, '/root/pypi/pkg1/2.6',
                     headers=dict(accept="text/html"))
    filesinfo = [tuple(t.text.strip() for t in x.findAll('td')[:3]) for x in r.html.select('.files tbody tr')]
    assert filesinfo == [('pkg1-2.6.zip', 'Source', '')]
    links = r.html.select('#content a')
    assert [(l.text, l.attrs['href']) for l in links] == [
        ("Simple index", "http://localhost/root/pypi/+simple/pkg1"),
        ("pkg1-2.6.zip", "http://localhost/root/pypi/+e/https_pypi.python.org_pkg/pkg1-2.6.zip"),
        ("https://pypi.python.org/pypi/pkg1/2.6/", "https://pypi.python.org/pypi/pkg1/2.6/")]


def test_version_view_root_pypi_external_files(mapp, testapp, pypistage):
    pypistage.mock_simple(
        "pkg1", '<a href="http://example.com/releases/pkg1-2.7.zip" /a>)')
    r = testapp.get('/root/pypi/pkg1/2.7', headers=dict(accept="text/html"))
    assert r.status_code == 200
    filesinfo = [tuple(t.text.strip() for t in x.findAll('td')[:3])
                 for x in r.html.select('.files tbody tr')]
    assert filesinfo == [('pkg1-2.7.zip', 'Source', '')]
    silink, link1, link2 = list(r.html.select("#content a"))
    assert silink.text == "Simple index"
    assert silink.attrs["href"] == "http://localhost/root/pypi/+simple/pkg1"
    assert link1.text == "pkg1-2.7.zip"
    assert link1.attrs["href"].endswith("pkg1-2.7.zip")
    assert link2.text == "https://pypi.python.org/pypi/pkg1/2.7/"
    assert link2.attrs["href"] == "https://pypi.python.org/pypi/pkg1/2.7/"


@pytest.mark.parametrize("url", [
    '/root/pypi/someproject',
    '/root/pypi/someproject/2.6'])
def test_root_pypi_upstream_error(url, mapp, testapp, pypistage):
    pypistage.mock_simple("someproject", status_code=404)
    r = testapp.get(url, headers=dict(accept="text/html"))
    assert r.status_code == 502
    content, = r.html.select('#content')
    text = re.sub('\s+', ' ', content.text.strip())
    assert text == 'Error An error has occurred: 502 Bad Gateway 404 status on GET https://pypi.python.org/simple/someproject/'


def test_error_html_only(mapp, testapp, monkeypatch):
    from pyramid.httpexceptions import HTTPBadGateway
    def error(self):
        raise HTTPBadGateway()
    monkeypatch.setattr("devpi_server.views.PyPIView.user_list", error)
    r = testapp.get("/", headers=dict(accept="application/json"))
    assert r.status_code == 502
    assert r.content_type != "text/html"
    assert "502 Bad Gateway" in r.text.splitlines()


@pytest.mark.with_notifier
def test_testdata(mapp, testapp):
    from test_devpi_server.example import tox_result_data
    api = mapp.create_and_use()
    mapp.set_versiondata(
        {"name": "pkg1", "version": "2.6", "description": "foo"})
    mapp.upload_file_pypi(
        "pkg1-2.6.tgz", b"123", "pkg1", "2.6", code=200, waithooks=True)
    path, = mapp.get_release_paths("pkg1")
    r = testapp.post(path, json.dumps(tox_result_data))
    assert r.status_code == 200
    r = testapp.xget(200, api.index, headers=dict(accept="text/html"))
    passed, = r.html.select('.passed')
    assert passed.text == 'tests'
    assert passed.attrs['href'].endswith(
        '/user1/dev/pkg1/2.6/+toxresults/pkg1-2.6.tgz')
    r = testapp.xget(200, api.index + '/pkg1/2.6', headers=dict(accept="text/html"))
    toxresult, = r.html.select('tbody .toxresults')
    links = toxresult.select('a')
    assert len(links) == 2
    assert 'passed' in links[0].attrs['class']
    assert 'foo linux2 py27' in links[0].text
    assert 'All toxresults' in links[1].text
    r = testapp.xget(200, links[0].attrs['href'])
    content = "\n".join([x.text.strip() for x in r.html.select('.toxresult')])
    assert "No setup performed" in content
    assert "everything fine" in content
    r = testapp.xget(200, links[1].attrs['href'])
    rows = [
        tuple(
            t.text.strip() if len(t.text.split()) < 2 else " ".join(t.text.split())
            for t in x.findAll('td'))
        for x in r.html.select('tbody tr')]
    assert rows == [
        ("pkg1-2.6.tgz.toxresult0", "foo", "linux2", "py27", "", "No setup performed Tests passed")]


def test_search_nothing(testapp):
    r = testapp.get('/+search?query=')
    assert r.status_code == 200
    assert r.html.select('.searchresults') == []
    content, = r.html.select('#content')
    assert content.text.strip() == 'Your search  did not match anything.'


def test_search_no_results(testapp):
    r = testapp.get('/+search?query=blubber')
    assert r.status_code == 200
    assert r.html.select('.searchresults') == []
    content, = r.html.select('#content')
    assert content.text.strip() == 'Your search blubber did not match anything.'


@pytest.mark.with_notifier
def test_search_docs(mapp, testapp):
    api = mapp.create_and_use()
    mapp.set_versiondata({
        "name": "pkg1",
        "version": "2.6",
        "description": "foo"}, waithooks=True)
    mapp.upload_file_pypi(
        "pkg1-2.6.tar.gz", b"content", "pkg1", "2.6")
    content = zip_dict(
        {"index.html": "\n".join([
            "<html>",
            "<head><title>Foo</title></head>",
            "<body>Bar</body>",
            "</html>"])})
    mapp.upload_doc("pkg1.zip", content, "pkg1", "2.6", code=200,
                    waithooks=True)
    r = testapp.get('/+search?query=bar')
    assert r.status_code == 200
    links = r.html.select('.searchresults a')
    assert [(l.text.strip(), l.attrs['href']) for l in links] == [
        ("pkg1-2.6", "http://localhost/%s/pkg1/2.6" % api.stagename),
        ("Foo", "http://localhost/%s/pkg1/2.6/+d/index.html" % api.stagename)]


@pytest.mark.with_notifier
def test_search_deleted_stage(mapp, testapp):
    api = mapp.create_and_use()
    mapp.set_versiondata({
        "name": "pkg1",
        "version": "2.6",
        "description": "foo"})
    mapp.delete_index(api.stagename, waithooks=True)
    r = testapp.xget(200, '/+search?query=pkg')
    content = r.html.select('#content')[0].text.strip()
    assert content == 'Your search pkg did not match anything.'


@pytest.mark.with_notifier
def test_search_deleted_package(mapp, testapp):
    mapp.create_and_use()
    mapp.set_versiondata({
        "name": "pkg1",
        "version": "2.6",
        "description": "foo"})
    mapp.delete_project('pkg1', waithooks=True)
    r = testapp.xget(200, '/+search?query=pkg')
    content = r.html.select('#content')[0].text.strip()
    assert content == 'Your search pkg did not match anything.'


@pytest.mark.with_notifier
def test_search_deleted_version(mapp, testapp):
    mapp.create_and_use()
    mapp.set_versiondata({
        "name": "pkg1",
        "version": "2.6",
        "summary": "foo"})
    mapp.set_versiondata({
        "name": "pkg1",
        "version": "2.7",
        "description": "bar"})
    mapp.delete_project("pkg1/2.7", waithooks=True)
    r = testapp.xget(200, '/+search?query=bar%20OR%20foo')
    search_results = r.html.select('.searchresults > dl')
    assert len(search_results) == 1
    links = search_results[0].findAll('a')
    assert [(l.text.strip(), l.attrs['href']) for l in links] == [
        ("pkg1-2.6", "http://localhost/user1/dev/pkg1/2.6"),
        ("Summary", "http://localhost/user1/dev/pkg1/2.6#summary")]


@pytest.mark.with_notifier
def test_search_deleted_all_versions(mapp, testapp):
    mapp.create_and_use()
    mapp.set_versiondata({
        "name": "pkg1",
        "version": "2.6",
        "summary": "foo"})
    mapp.set_versiondata({
        "name": "pkg1",
        "version": "2.7",
        "description": "bar"})
    mapp.delete_project("pkg1/2.6")
    mapp.delete_project("pkg1/2.7", waithooks=True)
    r = testapp.xget(200, '/+search?query=bar%20OR%20foo')
    content = r.html.select('#content')[0].text.strip()
    assert content == 'Your search bar OR foo did not match anything.'
    r = testapp.xget(200, '/+search?query=pkg')
    content = r.html.select('#content')[0].text.strip()
    assert content == 'Your search pkg did not match anything.'


def test_search_root_pypi(mapp, testapp, pypistage):
    from devpi_web.main import get_indexer
    pypistage.mock_simple("pkg1", '<a href="/pkg1-2.6.zip" /a>')
    pypistage.mock_simple("pkg2", '')
    indexer = get_indexer(mapp.xom.config)
    indexer.update_projects([
        dict(name=u'pkg1', user=u'root', index=u'pypi'),
        dict(name=u'pkg2', user=u'root', index=u'pypi')], clear=True)
    r = testapp.xget(200, '/+search?query=pkg')
    search_results = r.html.select('.searchresults > dl > dt')
    assert len(search_results) == 2
    links = search_results[0].findAll('a')
    assert sorted((l.text.strip(), l.attrs['href']) for l in links) == [
        ("pkg1", "http://localhost/root/pypi/pkg1")]
    links = search_results[1].findAll('a')
    assert sorted((l.text.strip(), l.attrs['href']) for l in links) == [
        ("pkg2", "http://localhost/root/pypi/pkg2")]


@pytest.mark.with_notifier
def test_indexing_doc_with_missing_title(mapp, testapp):
    mapp.create_and_use()
    content = zip_dict({"index.html": "<html><body>Foo</body></html>"})
    mapp.set_versiondata({"name": "pkg1", "version": "2.6"})
    mapp.upload_doc("pkg1.zip", content, "pkg1", "2.6", code=200,
                    waithooks=True)
    r = testapp.xget(200, '/+search?query=Foo')
    search_results = r.html.select('.searchresults > dl > dt')
    assert len(search_results) == 1
    links = search_results[0].findAll('a')
    assert sorted((l.text.strip(), l.attrs['href']) for l in links) == [
        ("pkg1-2.6", "http://localhost/user1/dev/pkg1/2.6")]


@pytest.mark.parametrize("pagecount, pagenum, expected", [
    (1, 1, [
        {'class': 'prev'}, {'class': 'current', 'title': 1}, {'class': 'next'}]),
    (2, 1, [
        {'class': 'prev'},
        {'class': 'current', 'title': 1},
        {'title': 2, 'url': u'search?page=2&query='},
        {'class': 'next', 'title': 'Next', 'url': 'search?page=2&query='}]),
    (2, 2, [
        {'class': 'prev', 'title': 'Prev', 'url': 'search?page=1&query='},
        {'title': 1, 'url': u'search?page=1&query='},
        {'class': 'current', 'title': 2},
        {'class': 'next'}]),
    (3, 1, [
        {'class': 'prev'},
        {'class': 'current', 'title': 1},
        {'title': 2, 'url': u'search?page=2&query='},
        {'title': 3, 'url': u'search?page=3&query='},
        {'class': 'next', 'title': 'Next', 'url': 'search?page=2&query='}]),
    (3, 2, [
        {'class': 'prev', 'title': 'Prev', 'url': 'search?page=1&query='},
        {'title': 1, 'url': u'search?page=1&query='},
        {'class': 'current', 'title': 2},
        {'title': 3, 'url': u'search?page=3&query='},
        {'class': 'next', 'title': 'Next', 'url': 'search?page=3&query='}]),
    (10, 2, [
        {'class': 'prev', 'title': 'Prev', 'url': 'search?page=1&query='},
        {'title': 1, 'url': u'search?page=1&query='},
        {'class': 'current', 'title': 2},
        {'title': 3, 'url': u'search?page=3&query='},
        {'title': 4, 'url': u'search?page=4&query='},
        {'title': 5, 'url': u'search?page=5&query='},
        {'title': u'\u2026'},
        {'title': 10, 'url': u'search?page=10&query='},
        {'class': 'next', 'title': 'Next', 'url': 'search?page=3&query='}])])
def test_search_batch_links(dummyrequest, pagecount, pagenum, expected):
    from devpi_web.views import SearchView
    view = SearchView(dummyrequest)
    items = [dict()]
    view.__dict__['search_result'] = dict(items=items, info=dict(
        pagecount=pagecount, pagenum=pagenum))
    dummyrequest.params['page'] = str(pagenum)
    dummyrequest.route_url = lambda r, **kw: "search?%s" % "&".join(
        "%s=%s" % x for x in sorted(kw['_query'].items()))
    assert view.batch_links == expected


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
        [('pkg1-2.6.tgz', 'http://localhost/{stage}/+f/202/cb962ac59075b/pkg1-2.6.tgz#md5=202cb962ac59075b964b07152d234b70')]),
    (
        "http://localhost:80/{stage}/pkg1/2.6",
        {'x-outside-url': 'http://example.com/foo'},
        '.files td:nth-of-type(1) a',
        [('pkg1-2.6.tgz', 'http://example.com/foo/{stage}/+f/202/cb962ac59075b/pkg1-2.6.tgz#md5=202cb962ac59075b964b07152d234b70')]),
    (
        "http://localhost:80/{stage}/pkg1/2.6",
        {'host': 'example.com'},
        '.files td:nth-of-type(1) a',
        [('pkg1-2.6.tgz', 'http://example.com/{stage}/+f/202/cb962ac59075b/pkg1-2.6.tgz#md5=202cb962ac59075b964b07152d234b70')]),
    (
        "http://localhost:80/{stage}/pkg1/2.6",
        {'host': 'example.com:3141'},
        '.files td:nth-of-type(1) a',
        [('pkg1-2.6.tgz', 'http://example.com:3141/{stage}/+f/202/cb962ac59075b/pkg1-2.6.tgz#md5=202cb962ac59075b964b07152d234b70')])])
def test_url_rewriting(url, headers, selector, expected, mapp, testapp):
    api = mapp.create_and_use()
    mapp.upload_file_pypi("pkg1-2.6.tgz", b"123", "pkg1", "2.6")
    url = url.format(stage=api.stagename)
    r = testapp.xget(200, url, headers=dict(accept="text/html", **headers))
    links = [
        (x.text.strip(), x.attrs.get('href'))
        for x in r.html.select(selector)]
    expected = [(t, u.format(stage=api.stagename)) for t, u in expected]
    assert links == expected


@pytest.mark.xfail(not server21_or_newer, reason="devpi-server < 2.1dev")
def test_static_404(testapp):
    r = testapp.xget(404, '/+static/foo.png')
    assert [x.text for x in r.html.select('#content p')] == [
        u'The following resource could not be found:',
        u'http://localhost/+static/foo.png']
