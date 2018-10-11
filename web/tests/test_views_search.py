# -*- coding: utf-8 -*-
from devpi_common.archive import zip_dict
import pytest
import re


def compareable_text(text):
    return re.sub(r'\s+', ' ', text.strip())


def test_search_nothing(testapp):
    r = testapp.get('/+search?query=')
    assert r.status_code == 200
    assert r.html.select('.searchresults') == []
    content, = r.html.select('#content')
    assert compareable_text(content.text) == 'Your search did not match anything.'


def test_search_no_results(testapp):
    r = testapp.get('/+search?query=blubber')
    assert r.status_code == 200
    assert r.html.select('.searchresults') == []
    content, = r.html.select('#content')
    assert compareable_text(content.text) == 'Your search blubber did not match anything.'


@pytest.mark.with_notifier
def test_search_docs(mapp, testapp):
    api = mapp.create_and_use()
    mapp.set_versiondata({
        "name": "pkg_hello",
        "version": "2.6",
        "description": "foo"}, waithooks=True)
    mapp.upload_file_pypi(
        "pkg_hello-2.6-py2.py3-none-any.whl", b"content", "pkg_hello", "2.6")
    content = zip_dict(
        {"index.html": "\n".join([
            "<html>",
            "<head><title>Foo</title></head>",
            "<body>Bar</body>",
            "</html>"])})
    mapp.upload_doc("pkg-hello-2.6.doc.zip", content, "pkg_hello", "2.6", code=200,
                    waithooks=True)
    r = testapp.get('/+search?query=bar')
    assert r.status_code == 200
    highlight = r.html.select('.searchresults dd dd')
    assert [compareable_text(x.text) for x in highlight] == ["Bar"]
    links = r.html.select('.searchresults a')
    assert [(compareable_text(l.text), l.attrs['href']) for l in links] == [
        ("pkg_hello-2.6", "http://localhost/%s/pkg-hello/2.6" % api.stagename),
        ("Foo", "http://localhost/%s/pkg-hello/2.6/+d/index.html" % api.stagename)]


@pytest.mark.with_notifier
def test_search_deleted_stage(mapp, testapp):
    api = mapp.create_and_use()
    mapp.set_versiondata({
        "name": "pkg1",
        "version": "2.6",
        "description": "foo"})
    mapp.delete_index(api.stagename, waithooks=True)
    r = testapp.xget(200, '/+search?query=pkg')
    content = compareable_text(r.html.select('#content')[0].text)
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
    content = compareable_text(r.html.select('#content')[0].text)
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
    assert [(compareable_text(l.text), l.attrs['href']) for l in links] == [
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
    content = compareable_text(r.html.select('#content')[0].text)
    assert content == 'Your search bar OR foo did not match anything.'
    r = testapp.xget(200, '/+search?query=pkg')
    content = compareable_text(r.html.select('#content')[0].text)
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
    assert sorted((compareable_text(l.text), l.attrs['href']) for l in links) == [
        ("pkg1", "http://localhost/root/pypi/pkg1")]
    links = search_results[1].findAll('a')
    assert sorted((compareable_text(l.text), l.attrs['href']) for l in links) == [
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
    assert sorted((compareable_text(l.text), l.attrs['href']) for l in links) == [
        ("pkg1-2.6", "http://localhost/user1/dev/pkg1/2.6")]


@pytest.mark.with_notifier
def test_indexing_doc_with_unicode(mapp, testapp):
    mapp.create_and_use()
    mapp.set_versiondata({"name": "pkg1", "version": "2.6"})
    content = zip_dict({"index.html": u'<html><meta charset="utf-8"><body>Föö</body></html>'.encode('utf-8')})
    mapp.upload_doc("pkg1.zip", content, "pkg1", "2.6", code=200,
                    waithooks=True)
    r = testapp.xget(200, '/+search?query=F%C3%B6%C3%B6')
    search_results = r.html.select('.searchresults > dl > dt')
    assert len(search_results) == 1


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


@pytest.mark.parametrize("pagecount, pagenum, expected", [
    (1, 1, [
        {'class': 'prev'},
        {'title': 1, 'url': u'search?page=1&query='},
        {'class': 'next'}]),
    (2, 1, [
        {'class': 'prev'},
        {'title': 1, 'url': u'search?page=1&query='},
        {'title': 2, 'url': u'search?page=2&query='},
        {'class': 'next', 'title': 'Next', 'url': 'search?page=2&query='}])])
def test_search_batch_links_page_too_big(dummyrequest, pagecount, pagenum, expected):
    from devpi_web.views import SearchView
    view = SearchView(dummyrequest)
    items = [dict()]
    view.__dict__['search_result'] = dict(items=items, info=dict(
        pagecount=pagecount, pagenum=pagenum))
    dummyrequest.params['page'] = str(132)
    dummyrequest.route_url = lambda r, **kw: "search?%s" % "&".join(
        "%s=%s" % x for x in sorted(kw['_query'].items()))
    assert view.batch_links == expected


def get_xmlrpc_data(body):
    from devpi_web.views import DefusedExpatParser, Unmarshaller
    unmarshaller = Unmarshaller()
    parser = DefusedExpatParser(unmarshaller)
    parser.feed(body)
    parser.close()
    return (unmarshaller.close(), unmarshaller.getmethodname())


@pytest.mark.with_notifier
def test_pip_search(mapp, pypistage, testapp):
    from devpi_web.main import get_indexer
    from operator import itemgetter
    api = mapp.create_and_use(indexconfig=dict(bases=["root/pypi"]))
    pypistage.mock_simple("pkg1", '<a href="/pkg1-2.6.zip" /a>')
    pypistage.mock_simple("pkg2", '')
    # we need to set dummy data, so we can use waithooks
    mapp.set_versiondata({"name": "pkg2", "version": "2.7"}, waithooks=True)
    # now we can access the indexer directly without causing locking issues
    indexer = get_indexer(mapp.xom.config)
    indexer.update_projects([
        dict(name=u'pkg1', user=u'root', index=u'pypi'),
        dict(name=u'pkg2', user=u'root', index=u'pypi')], clear=True)
    mapp.set_versiondata({
        "name": "pkg2",
        "version": "2.7",
        "summary": "foo",
        "description": "bar"}, waithooks=True)
    headers = {'Content-Type': 'text/xml'}
    body = b"""<?xml version='1.0'?>
        <methodCall>
        <methodName>search</methodName>
        <params>
        <param>
        <value><struct>
        <member>
        <name>summary</name>
        <value><array><data>
        <value><string>pkg</string></value>
        </data></array></value>
        </member>
        <member>
        <name>name</name>
        <value><array><data>
        <value><string>pkg</string></value>
        </data></array></value>
        </member>
        </struct></value>
        </param>
        <param>
        <value><string>or</string></value>
        </param>
        </params>
        </methodCall>
        """
    r = testapp.post('/%s/' % api.stagename, body, headers=headers)
    assert r.status_code == 200
    (data, method) = get_xmlrpc_data(r.body)
    assert method is None
    items = sorted(data[0], key=itemgetter('_pypi_ordering', 'name'))
    assert len(items) == 2
    # we only use cached data, so the version is empty
    assert items[0]['name'] == 'pkg1'
    assert items[0]['summary'] == '[root/pypi]'
    assert items[0]['version'] == ''
    assert items[1]['name'] == 'pkg2'
    assert items[1]['summary'] == '[user1/dev] foo'
    assert items[1]['version'] == '2.7'
    # without root/pypi, we only get data from the private index
    r = mapp.modify_index(api.stagename, indexconfig=dict(bases=()))
    r = testapp.post('/%s/' % api.stagename, body, headers=headers)
    assert r.status_code == 200
    (data, method) = get_xmlrpc_data(r.body)
    assert method is None
    items = data[0]
    assert len(items) == 1
    assert items[0]['name'] == 'pkg2'


def test_make_more_url_params_with_page():
    from devpi_web.views import make_more_url_params
    params = {u'query': u'devpi', u'page': 11}
    path = '/root/dev/devpi'
    new_params = make_more_url_params(params, path)
    assert 'page' not in new_params
    assert path in new_params['query']
    assert params['query'] in new_params['query']


def test_make_more_url_params():
    from devpi_web.views import make_more_url_params
    params = {u'query': u'devpi'}
    path = '/root/dev/devpi'
    new_params = make_more_url_params(params, path)
    assert 'page' not in new_params
    assert path in new_params['query']
    assert params['query'] in new_params['query']
