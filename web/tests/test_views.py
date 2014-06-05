from devpi_common.archive import zip_dict
import py
import pytest


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


def test_docs_raw_view(mapp, testapp):
    api = mapp.create_and_use()
    content = zip_dict({"index.html": "<html/>"})
    mapp.upload_doc("pkg1.zip", content, "pkg1", "2.6", code=400)
    mapp.register_metadata({"name": "pkg1", "version": "2.6"})
    mapp.upload_doc("pkg1.zip", content, "pkg1", "2.6", code=200)
    r = testapp.get(api.index + "/pkg1/2.6/+doc/")
    assert r.status_code == 302
    r = testapp.get(r.location)
    assert r.status_code == 200
    r = testapp.get("/blubber/blubb/pkg1/2.6/+doc/index.html")
    assert r.status_code == 404
    content, = r.html.select('#content')
    assert content.text.strip() == 'The stage blubber/blubb could not be found.'
    r = testapp.get(api.index + "/pkg1/2.7/+doc/index.html")
    assert r.status_code == 404
    content, = r.html.select('#content')
    assert content.text.strip() == 'No documentation available.'
    r = testapp.get(api.index + "/pkg1/2.6/+doc/foo.html")
    assert r.status_code == 404
    content, = r.html.select('#content')
    assert content.text.strip() == 'File foo.html not found in documentation.'


def test_docs_view(mapp, testapp):
    api = mapp.create_and_use()
    content = zip_dict({"index.html": "<html/>"})
    mapp.upload_doc("pkg1.zip", content, "pkg1", "2.6", code=400)
    mapp.register_metadata({"name": "pkg1", "version": "2.6"})
    mapp.upload_doc("pkg1.zip", content, "pkg1", "2.6", code=200)
    r = testapp.get(api.index + "/pkg1/2.6/+d/")
    assert r.status_code == 302
    r = testapp.get(r.location)
    assert r.status_code == 200
    iframe, = r.html.findAll('iframe')
    assert iframe.attrs['src'] == api.index + "/pkg1/2.6/+doc/index.html"
    r = testapp.get("/blubber/blubb/pkg1/2.6/+d/index.html")
    assert r.status_code == 404
    content, = r.html.select('#content')
    assert content.text.strip() == 'The stage blubber/blubb could not be found.'
    r = testapp.get(api.index + "/pkg1/2.7/+d/index.html")
    assert r.status_code == 404
    content, = r.html.select('#content')
    assert content.text.strip() == 'No documentation available.'
    r = testapp.get(api.index + "/pkg1/2.6/+d/foo.html")
    assert r.status_code == 404
    content, = r.html.select('#content')
    assert content.text.strip() == 'File foo.html not found in documentation.'


def test_not_found_redirect(testapp):
    r = testapp.get('/root/pypi/?foo=bar', headers=dict(accept="text/html"))
    assert r.status_code == 302
    assert r.location == 'http://localhost/root/pypi?foo=bar'


def test_root_view(testapp):
    r = testapp.get('/', headers=dict(accept="text/html"))
    assert r.status_code == 200
    links = r.html.select('#content a')
    assert [(l.text, l.attrs['href']) for l in links] == [
        ("root/pypi", "http://localhost:80/root/pypi")]


def test_root_view_with_index(mapp, testapp):
    api = mapp.create_and_use()
    r = testapp.get('/', headers=dict(accept="text/html"))
    assert r.status_code == 200
    links = r.html.select('#content a')
    assert [(l.text, l.attrs['href']) for l in links] == [
        ("root/pypi", "http://localhost:80/root/pypi"),
        (api.stagename, "http://localhost:80/%s" % api.stagename)]


def test_index_view_root_pypi(testapp):
    r = testapp.get('/root/pypi', headers=dict(accept="text/html"))
    assert r.status_code == 200
    links = r.html.select('#content a')
    assert [(l.text, l.attrs['href']) for l in links] == [
        ("simple index", "http://localhost:80/root/pypi/+simple/")]


def test_index_view(mapp, testapp):
    api = mapp.create_and_use()
    r = testapp.get(api.index, headers=dict(accept="text/html"))
    assert r.status_code == 200
    links = r.html.select('#content a')
    assert [(l.text, l.attrs['href']) for l in links] == [
        ("simple index", "http://localhost:80/%s/+simple/" % api.stagename),
        ("root/pypi", "http://localhost:80/root/pypi"),
        ("simple", "http://localhost:80/root/pypi/+simple/")]


def test_index_not_found(testapp):
    r = testapp.get("/blubber/blubb", headers=dict(accept="text/html"))
    assert r.status_code == 404
    content, = r.html.select('#content')
    assert content.text.strip() == 'The stage blubber/blubb could not be found.'


def test_index_view_project_info(mapp, testapp):
    api = mapp.create_and_use()
    mapp.register_metadata({"name": "pkg1", "version": "2.6"})
    r = testapp.get(api.index, headers=dict(accept="text/html"))
    assert r.status_code == 200
    links = r.html.select('#content a')
    assert [(l.text, l.attrs['href']) for l in links] == [
        ("simple index", "http://localhost:80/%s/+simple/" % api.stagename),
        ("pkg1-2.6 info page", "http://localhost:80/%s/pkg1/2.6" % api.stagename),
        ("root/pypi", "http://localhost:80/root/pypi"),
        ("simple", "http://localhost:80/root/pypi/+simple/")]


def test_index_view_project_files(mapp, testapp):
    api = mapp.create_and_use()
    mapp.upload_file_pypi(
        "pkg1-2.6.tar.gz", b"content", "pkg1", "2.6")
    r = testapp.get(api.index, headers=dict(accept="text/html"))
    assert r.status_code == 200
    links = r.html.select('#content a')
    assert [(l.text, l.attrs['href']) for l in links] == [
        ("simple index", "http://localhost:80/%s/+simple/" % api.stagename),
        ("pkg1-2.6 info page", "http://localhost:80/%s/pkg1/2.6" % api.stagename),
        ("pkg1-2.6.tar.gz", "http://localhost/%s/+f/9a0364b9e99bb480dd25e1f0284c8555/pkg1-2.6.tar.gz#md5=9a0364b9e99bb480dd25e1f0284c8555" % api.stagename),
        ("root/pypi", "http://localhost:80/root/pypi"),
        ("simple", "http://localhost:80/root/pypi/+simple/")]
    mapp.upload_file_pypi(
        "pkg1-2.6.zip", b"contentzip", "pkg1", "2.6")
    r = testapp.get(api.index, headers=dict(accept="text/html"))
    assert r.status_code == 200
    links = r.html.select('#content a')
    assert [(l.text, l.attrs['href']) for l in links] == [
        ("simple index", "http://localhost:80/%s/+simple/" % api.stagename),
        ("pkg1-2.6 info page", "http://localhost:80/%s/pkg1/2.6" % api.stagename),
        ("pkg1-2.6.tar.gz", "http://localhost/%s/+f/9a0364b9e99bb480dd25e1f0284c8555/pkg1-2.6.tar.gz#md5=9a0364b9e99bb480dd25e1f0284c8555" % api.stagename),
        ("pkg1-2.6.zip", "http://localhost/%s/+f/52360ae08d733016c5603d54b06b5300/pkg1-2.6.zip#md5=52360ae08d733016c5603d54b06b5300" % api.stagename),
        ("root/pypi", "http://localhost:80/root/pypi"),
        ("simple", "http://localhost:80/root/pypi/+simple/")]


def test_index_view_project_docs(mapp, testapp):
    api = mapp.create_and_use()
    mapp.register_metadata({"name": "pkg1", "version": "2.6"})
    content = zip_dict({"index.html": "<html/>"})
    mapp.upload_doc("pkg1.zip", content, "pkg1", "2.6", code=200)
    r = testapp.get(api.index, headers=dict(accept="text/html"))
    assert r.status_code == 200
    links = r.html.select('#content a')
    assert [(l.text, l.attrs['href']) for l in links] == [
        ("simple index", "http://localhost:80/%s/+simple/" % api.stagename),
        ("pkg1-2.6 info page", "http://localhost:80/%s/pkg1/2.6" % api.stagename),
        ("pkg1-2.6 docs", "http://localhost:80/%s/pkg1/2.6/+d/index.html" % api.stagename),
        ("root/pypi", "http://localhost:80/root/pypi"),
        ("simple", "http://localhost:80/root/pypi/+simple/")]


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
        ("2.7", "http://localhost:80/%s/pkg1/2.7" % api.stagename),
        ("2.6", "http://localhost:80/%s/pkg1/2.6" % api.stagename)]


def test_project_not_found(mapp, testapp):
    api = mapp.create_and_use()
    r = testapp.get("/blubber/blubb/pkg1", headers=dict(accept="text/html"))
    assert r.status_code == 404
    content, = r.html.select('#content')
    assert content.text.strip() == 'The stage blubber/blubb could not be found.'
    r = testapp.get(api.index + "/pkg1", headers=dict(accept="text/html"))
    assert r.status_code == 404
    content, = r.html.select('#content')
    assert content.text.strip() == 'The project pkg1 does not exist.'


def test_project_view_root_pypi(mapp, testapp):
    with mapp.xom.keyfs.transaction():
        pypistage = mapp.xom.model.getstage('root/pypi')
        pypistage.name2serials['pkg1'] = {}
        cache = {
            "serial": 0,
            "entrylist": [
                'root/pypi/+f/9a0364b9e99bb480dd25e1f0284c8555/pkg1-2.7.zip',
                'root/pypi/+f/52360ae08d733016c5603d54b06b5300/pkg1-2.6.zip'],
            "projectname": 'pkg1'}
        pypistage.keyfs.PYPILINKS(name='pkg1').set(cache)

    r = testapp.get('/root/pypi/pkg1', headers=dict(accept="text/html"))
    assert r.status_code == 200
    links = r.html.select('#content a')
    assert [(l.text, l.attrs['href']) for l in links] == [
        ("2.7", "http://localhost:80/root/pypi/pkg1/2.7"),
        ("2.6", "http://localhost:80/root/pypi/pkg1/2.6")]


def test_version_view(mapp, testapp):
    api = mapp.create_and_use()
    mapp.upload_file_pypi(
        "pkg1-2.6.tar.gz", b"content", "pkg1", "2.6")
    mapp.upload_file_pypi(
        "pkg1-2.6.zip", b"contentzip", "pkg1", "2.6")
    content = zip_dict({"index.html": "<html/>"})
    mapp.upload_doc("pkg1.zip", content, "pkg1", "2.6", code=200)
    mapp.register_metadata({
        "name": "pkg1",
        "version": "2.6",
        "author": "Foo Bear",
        "description": "foo"})
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
        'utf-8') == '<p>foo</p>'
    filesinfo = [tuple(t.text for t in x.findAll('td')) for x in r.html.select('.files tr')]
    assert filesinfo == [
        ('pkg1-2.6.tar.gz', 'Source', '', '7 bytes', '9a0364b9e99bb480dd25e1f0284c8555'),
        ('pkg1-2.6.zip', 'Source', '', '10 bytes', '52360ae08d733016c5603d54b06b5300')]
    links = r.html.select('#content a')
    assert [(l.text, l.attrs['href']) for l in links] == [
        ("Documentation", "http://localhost:80/%s/pkg1/2.6/+d/index.html" % api.stagename),
        ("pkg1-2.6.tar.gz", "http://localhost/%s/+f/9a0364b9e99bb480dd25e1f0284c8555/pkg1-2.6.tar.gz#md5=9a0364b9e99bb480dd25e1f0284c8555" % api.stagename),
        ("pkg1-2.6.zip", "http://localhost/%s/+f/52360ae08d733016c5603d54b06b5300/pkg1-2.6.zip#md5=52360ae08d733016c5603d54b06b5300" % api.stagename)]


def test_version_not_found(mapp, testapp):
    api = mapp.create_and_use()
    mapp.upload_file_pypi(
        "pkg1-2.6.tar.gz", b"content", "pkg1", "2.6")
    r = testapp.get("/blubber/blubb/pkg1/2.6", headers=dict(accept="text/html"))
    assert r.status_code == 404
    content, = r.html.select('#content')
    assert content.text.strip() == 'The stage blubber/blubb could not be found.'
    r = testapp.get(api.index + "/pkg2/2.6", headers=dict(accept="text/html"))
    assert r.status_code == 404
    content, = r.html.select('#content')
    assert content.text.strip() == 'The project pkg2 does not exist.'
    r = testapp.get(api.index + "/pkg1/2.7", headers=dict(accept="text/html"))
    assert r.status_code == 404
    content, = r.html.select('#content')
    assert content.text.strip() == 'The version 2.7 of project pkg1 does not exist.'


def test_version_view_root_pypi(mapp, testapp):
    with mapp.xom.keyfs.transaction():
        pypistage = mapp.xom.model.getstage('root/pypi')
        pypistage.name2serials['pkg1'] = {}
        cache = {
            "serial": 0,
            "entrylist": ['root/pypi/+f/52360ae08d733016c5603d54b06b5300/pkg1-2.6.zip'],
            "projectname": 'pkg1'}
        pypistage.keyfs.PYPILINKS(name='pkg1').set(cache)
    r = testapp.get('/root/pypi/pkg1/2.6', headers=dict(accept="text/html"))
    assert r.status_code == 200
    filesinfo = [tuple(t.text for t in x.findAll('td')) for x in r.html.select('.files tr')]
    assert filesinfo == [('pkg1-2.6.zip', 'Source', '', '', '')]
    links = r.html.select('#content a')
    assert [(l.text, l.attrs['href']) for l in links] == [
        ("pkg1-2.6.zip", "http://localhost/root/pypi/+f/52360ae08d733016c5603d54b06b5300/pkg1-2.6.zip"),
        ("https://pypi.python.org/pypi/pkg1/2.6/", "https://pypi.python.org/pypi/pkg1/2.6/")]


def test_version_view_root_pypi_external_files(mapp, testapp):
    with mapp.xom.keyfs.transaction():
        pypistage = mapp.xom.model.getstage('root/pypi')
        pypistage.name2serials['pkg1'] = {}
        cache = {
            "serial": 0,
            "entrylist": ['root/pypi/+e/http/example.com/releases/pkg1-2.7.zip'],
            "projectname": 'pkg1'}
        pypistage.keyfs.PYPILINKS(name='pkg1').set(cache)
    r = testapp.get('/root/pypi/pkg1/2.7', headers=dict(accept="text/html"))
    assert r.status_code == 200
    filesinfo = [tuple(t.text for t in x.findAll('td')) for x in r.html.select('.files tr')]
    assert filesinfo == [('pkg1-2.7.zip', 'Source', '', '', '')]
    links = r.html.select('#content a')
    assert [(l.text, l.attrs['href']) for l in links] == [
        ("pkg1-2.7.zip", "http://localhost/root/pypi/+e/http/example.com/releases/pkg1-2.7.zip"),
        ("https://pypi.python.org/pypi/pkg1/2.7/", "https://pypi.python.org/pypi/pkg1/2.7/")]


def test_search_docs(mapp, testapp):
    api = mapp.create_and_use()
    mapp.register_metadata({
        "name": "pkg1",
        "version": "2.6",
        "description": "foo"})
    mapp.upload_file_pypi(
        "pkg1-2.6.tar.gz", b"content", "pkg1", "2.6")
    content = zip_dict(
        {"index.html": "\n".join([
            "<html>",
            "<head><title>Foo</title></head>",
            "<body>Bar</body>",
            "</html>"])})
    mapp.upload_doc("pkg1.zip", content, "pkg1", "2.6", code=200)
    r = testapp.get('/+search?query=bar')
    assert r.status_code == 200
    links = r.html.select('.searchresults a')
    assert [(l.text.strip(), l.attrs['href']) for l in links] == [
        ("pkg1-2.6", "http://localhost:80/%s/pkg1/2.6" % api.stagename),
        ("Foo", "http://localhost:80/%s/pkg1/2.6/+d/index.html" % api.stagename)]
