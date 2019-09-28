import sys
from devpi_common.archive import zip_dict
import py
import pytest
import re


pytestmark = pytest.mark.xfail(sys.platform.startswith("win"), run=False, reason="flaky test on windows")


def compareable_text(text):
    return re.sub(r'\s+', ' ', text.strip())


@pytest.mark.with_notifier
def test_docs_raw_view(mapp, testapp):
    api = mapp.create_and_use()
    content = zip_dict({"index.html": "<html/>"})
    mapp.set_versiondata({"name": "pkg1", "version": "2.6"})
    mapp.upload_doc("pkg1.zip", content, "pkg1", "2.6", code=200,
                    waithooks=True)
    r = testapp.xget(302, api.index + "/pkg1/2.6/+doc/")
    r = testapp.xget(200, r.location)
    assert r.cache_control.no_cache is None
    r = testapp.xget(302, api.index + "/pkg1/latest/+doc/")
    r = testapp.xget(200, r.location)
    assert r.cache_control.no_cache
    r = testapp.xget(302, api.index + "/pkg1/stable/+doc/")
    r = testapp.xget(200, r.location)
    assert r.cache_control.no_cache
    r = testapp.xget(404, "/blubber/blubb/pkg1/2.6/+doc/index.html")
    content, = r.html.select('#content')
    assert 'The stage blubber/blubb could not be found.' in compareable_text(content.text)
    r = testapp.xget(404, api.index + "/pkg1/2.7/+doc/index.html")
    content, = r.html.select('#content')
    assert 'No documentation available.' in compareable_text(content.text)
    r = testapp.xget(404, api.index + "/pkg1/2.6/+doc/foo.html")
    content, = r.html.select('#content')
    assert 'File foo.html not found in documentation.' in compareable_text(content.text)


@pytest.mark.with_notifier
def test_docs_view(mapp, testapp):
    api = mapp.create_and_use()
    content = zip_dict({"index.html": "<html/>"})
    mapp.set_versiondata({"name": "pkg1", "version": "2.6"})
    mapp.upload_doc("pkg1.zip", content, "pkg1", "2.6", code=200,
                    waithooks=True)
    r = testapp.xget(302, api.index + "/pkg1/2.6/+d/")
    r = testapp.xget(200, r.location)
    iframe, = r.html.findAll('iframe')
    assert iframe.attrs['src'] == api.index + "/pkg1/2.6/+doc/index.html"
    r = testapp.xget(404, "/blubber/blubb/pkg1/2.6/+d/index.html")
    content, = r.html.select('#content')
    assert 'The stage blubber/blubb could not be found.' in compareable_text(content.text)
    r = testapp.xget(404, api.index + "/pkg1/2.7/+d/index.html")
    content, = r.html.select('#content')
    assert 'No documentation available.' in compareable_text(content.text)
    r = testapp.xget(404, api.index + "/pkg1/2.6/+d/foo.html")
    content, = r.html.select('#content')
    assert 'File foo.html not found in documentation.' in compareable_text(content.text)
    r = testapp.xget(200, api.index + "/pkg1/2.6/+d/index.html?foo=bar")
    (iframe,) = r.html.select('iframe')
    assert iframe.attrs['src'].endswith("index.html?foo=bar")


@pytest.mark.with_notifier
def test_docs_raw_projectname(mapp, testapp):
    api = mapp.create_and_use()
    content = zip_dict({"index.html": "<html><body>foo</body></html>"})
    mapp.set_versiondata({
        "name": "pkg_hello", "version": "1.0"})
    mapp.upload_doc(
        "pkg-hello.zip", content, "pkg-hello", "1.0", code=200, waithooks=True)
    location = '%s/pkg_hello/1.0/' % api.index
    r = testapp.xget(200, location, headers=dict(accept="text/html"))
    navlinks = dict(
        (l.text, l.attrs['href'])
        for l in r.html.select('.projectnavigation a'))
    assert 'Documentation' in navlinks
    # the regular name should work
    location = '%s/pkg_hello/1.0/+doc/index.html' % api.index
    r = testapp.xget(200, location, headers=dict(accept="text/html"))
    html = py.builtin._totext(r.html.renderContents().strip(), 'utf-8')
    assert '<html><body>foo</body></html>' == html
    # as well as the normalized name
    location = '%s/pkg-hello/1.0/+doc/index.html' % api.index
    r = testapp.xget(200, location, headers=dict(accept="text/html"))
    html = py.builtin._totext(r.html.renderContents().strip(), 'utf-8')
    assert '<html><body>foo</body></html>' == html


@pytest.mark.with_notifier
def test_docs_show_projectname(mapp, testapp):
    api = mapp.create_and_use()
    content = zip_dict({"index.html": "<html><body>foo</body></html>"})
    mapp.set_versiondata({
        "name": "pkg_hello", "version": "1.0"})
    mapp.upload_doc(
        "pkg-hello.zip", content, "pkg-hello", "1.0", code=200, waithooks=True)
    location = '%s/pkg-hello/1.0/+d/index.html' % api.index
    r = testapp.xget(200, location, headers=dict(accept="text/html"))
    iframe, = r.html.findAll('iframe')
    assert iframe.attrs['src'] == api.index + "/pkg-hello/1.0/+doc/index.html"


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
    assert navigation_links[4].text == '2.6'
    # there is no warning
    assert r.html.select('.infonote') == []
    # and the content matches
    r = testapp.xget(200, iframe.attrs['src'])
    assert r.text == "<html><body>2.6</body></html>"
    # now we register a newer version, but docs should still be 2.6
    mapp.set_versiondata({"name": "pkg1", "version": "2.7"}, waithooks=True)
    r = testapp.xget(200, api.index + "/pkg1/latest/+d/index.html")
    iframe, = r.html.findAll('iframe')
    assert iframe.attrs['src'] == api.index + "/pkg1/latest/+doc/index.html"
    # navigation shows latest registered version
    navigation_links = r.html.select("#navigation a")
    assert navigation_links[4].text == '2.7'
    # there is a warning
    assert [x.text.strip() for x in r.html.select('.infonote')] == [
        "The latest available documentation (version 2.6) isn't for the latest available package version."]
    # and the content is from older uploaded docs
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
    assert navigation_links[4].text == '2.7'
    # there is no warning anymore
    assert r.html.select('.infonote') == []
    # and the content is from newest docs
    r = testapp.xget(200, iframe.attrs['src'])
    assert r.text == "<html><body>2.7</body></html>"


@pytest.mark.with_notifier
def test_docs_stable(mapp, testapp):
    api = mapp.create_and_use()
    content = zip_dict({"index.html": "<html><body>2.6</body></html>"})
    mapp.set_versiondata({"name": "pkg1", "version": "2.6"})
    mapp.upload_doc("pkg1.zip", content, "pkg1", "2.6", code=200,
                    waithooks=True)
    r = testapp.xget(200, api.index + "/pkg1/stable/+d/index.html")
    iframe, = r.html.findAll('iframe')
    assert iframe.attrs['src'] == api.index + "/pkg1/stable/+doc/index.html"
    # navigation shows stable registered version
    navigation_links = r.html.select("#navigation a")
    assert navigation_links[4].text == '2.6'
    # there is no warning
    assert r.html.select('.infonote') == []
    # and the content matches
    r = testapp.xget(200, iframe.attrs['src'])
    assert r.text == "<html><body>2.6</body></html>"
    # now we register a newer version, but docs should still be 2.6
    mapp.set_versiondata({"name": "pkg1", "version": "2.7.a1"}, waithooks=True)
    r = testapp.xget(200, api.index + "/pkg1/stable/+d/index.html")
    iframe, = r.html.findAll('iframe')
    assert iframe.attrs['src'] == api.index + "/pkg1/stable/+doc/index.html"
    # navigation shows stable registered version
    navigation_links = r.html.select("#navigation a")
    assert navigation_links[4].text == '2.6'
    # there is no warning
    assert r.html.select('.infonote') == []
    # and the content is also from stable docs
    r = testapp.xget(200, iframe.attrs['src'])
    assert r.text == "<html><body>2.6</body></html>"
    # now we upload newer docs
    content = zip_dict({"index.html": "<html><body>2.7.a1</body></html>"})
    mapp.upload_doc("pkg1.zip", content, "pkg1", "2.7.a1", code=200,
                    waithooks=True)
    r = testapp.xget(200, api.index + "/pkg1/stable/+d/index.html")
    iframe, = r.html.findAll('iframe')
    assert iframe.attrs['src'] == api.index + "/pkg1/stable/+doc/index.html"
    # navigation shows stable registered version
    navigation_links = r.html.select("#navigation a")
    assert navigation_links[4].text == '2.6'
    # showing latest available version
    assert [x.text.strip() for x in r.html.select('.infonote')] == [
        "Latest documentation"]
    # and the content is also still from stable docs
    r = testapp.xget(200, iframe.attrs['src'])
    assert r.text == "<html><body>2.6</body></html>"
    # now we register a newer stable version, but docs should still be 2.6
    mapp.set_versiondata({"name": "pkg1", "version": "2.7"}, waithooks=True)
    r = testapp.xget(200, api.index + "/pkg1/stable/+d/index.html")
    iframe, = r.html.findAll('iframe')
    assert iframe.attrs['src'] == api.index + "/pkg1/stable/+doc/index.html"
    # navigation shows latest registered stable version
    navigation_links = r.html.select("#navigation a")
    assert navigation_links[4].text == '2.7'
    # there is a warning
    assert [x.text.strip() for x in r.html.select('.infonote')] == [
        "The latest available documentation (version 2.6) isn't for the latest available package version.",
        "Latest documentation"]
    # and the content is from older stable upload
    r = testapp.xget(200, iframe.attrs['src'])
    assert r.text == "<html><body>2.6</body></html>"
    # now we upload newer docs
    content = zip_dict({"index.html": "<html><body>2.7</body></html>"})
    mapp.upload_doc("pkg1.zip", content, "pkg1", "2.7", code=200,
                    waithooks=True)
    r = testapp.xget(200, api.index + "/pkg1/stable/+d/index.html")
    iframe, = r.html.findAll('iframe')
    assert iframe.attrs['src'] == api.index + "/pkg1/stable/+doc/index.html"
    # navigation shows latest registered stable version
    navigation_links = r.html.select("#navigation a")
    assert navigation_links[4].text == '2.7'
    # no warning anymore
    assert r.html.select('.infonote') == []
    # the content is now latest stable docs
    r = testapp.xget(200, iframe.attrs['src'])
    assert r.text == "<html><body>2.7</body></html>"
