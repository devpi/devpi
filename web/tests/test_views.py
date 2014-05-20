from devpi_common.archive import zip_dict
import py


def test_docs_view(mapp, testapp):
    api = mapp.create_and_use()
    content = zip_dict({"index.html": "<html/>"})
    mapp.upload_doc("pkg1.zip", content, "pkg1", "2.6", code=400)
    mapp.register_metadata({"name": "pkg1", "version": "2.6"})
    mapp.upload_doc("pkg1.zip", content, "pkg1", "2.6", code=200)
    r = testapp.get(api.index + "/pkg1/2.6/+doc/index.html")
    assert r.status_code == 200


def test_root_view(testapp):
    r = testapp.get('/', headers=dict(accept="text/html"))
    assert r.status_code == 200
    links = r.html.findAll('a')
    assert [(l.text, l.attrs['href']) for l in links] == [
        ("root/pypi", "http://localhost:80/root/pypi")]


def test_root_view_with_index(mapp, testapp):
    api = mapp.create_and_use()
    r = testapp.get('/', headers=dict(accept="text/html"))
    assert r.status_code == 200
    links = r.html.findAll('a')
    assert [(l.text, l.attrs['href']) for l in links] == [
        ("root/pypi", "http://localhost:80/root/pypi"),
        (api.stagename, "http://localhost:80/%s" % api.stagename)]


def test_index_view_root_pypi(testapp):
    r = testapp.get('/root/pypi', headers=dict(accept="text/html"))
    assert r.status_code == 200
    links = r.html.findAll('a')
    assert [(l.text, l.attrs['href']) for l in links] == [
        ("simple index", "http://localhost:80/root/pypi/+simple/")]


def test_index_view(mapp, testapp):
    api = mapp.create_and_use()
    r = testapp.get(api.index, headers=dict(accept="text/html"))
    assert r.status_code == 200
    links = r.html.findAll('a')
    assert [(l.text, l.attrs['href']) for l in links] == [
        ("simple index", "http://localhost:80/%s/+simple/" % api.stagename),
        ("root/pypi", "http://localhost:80/root/pypi"),
        ("simple", "http://localhost:80/root/pypi/+simple/")]


def test_index_view_project_info(mapp, testapp):
    api = mapp.create_and_use()
    mapp.register_metadata({"name": "pkg1", "version": "2.6"})
    r = testapp.get(api.index, headers=dict(accept="text/html"))
    assert r.status_code == 200
    links = r.html.findAll('a')
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
    links = r.html.findAll('a')
    assert [(l.text, l.attrs['href']) for l in links] == [
        ("simple index", "http://localhost:80/%s/+simple/" % api.stagename),
        ("pkg1-2.6 info page", "http://localhost:80/%s/pkg1/2.6" % api.stagename),
        ("pkg1-2.6.tar.gz", "http://localhost:80/%s/+f/9a0364b9e99bb480dd25e1f0284c8555/pkg1-2.6.tar.gz" % api.stagename),
        ("root/pypi", "http://localhost:80/root/pypi"),
        ("simple", "http://localhost:80/root/pypi/+simple/")]
    mapp.upload_file_pypi(
        "pkg1-2.6.zip", b"contentzip", "pkg1", "2.6")
    r = testapp.get(api.index, headers=dict(accept="text/html"))
    assert r.status_code == 200
    links = r.html.findAll('a')
    assert [(l.text, l.attrs['href']) for l in links] == [
        ("simple index", "http://localhost:80/%s/+simple/" % api.stagename),
        ("pkg1-2.6 info page", "http://localhost:80/%s/pkg1/2.6" % api.stagename),
        ("pkg1-2.6.tar.gz", "http://localhost:80/%s/+f/9a0364b9e99bb480dd25e1f0284c8555/pkg1-2.6.tar.gz" % api.stagename),
        ("pkg1-2.6.zip", "http://localhost:80/%s/+f/52360ae08d733016c5603d54b06b5300/pkg1-2.6.zip" % api.stagename),
        ("root/pypi", "http://localhost:80/root/pypi"),
        ("simple", "http://localhost:80/root/pypi/+simple/")]


def test_index_view_project_docs(mapp, testapp):
    api = mapp.create_and_use()
    mapp.register_metadata({"name": "pkg1", "version": "2.6"})
    content = zip_dict({"index.html": "<html/>"})
    mapp.upload_doc("pkg1.zip", content, "pkg1", "2.6", code=200)
    r = testapp.get(api.index, headers=dict(accept="text/html"))
    assert r.status_code == 200
    links = r.html.findAll('a')
    assert [(l.text, l.attrs['href']) for l in links] == [
        ("simple index", "http://localhost:80/%s/+simple/" % api.stagename),
        ("pkg1-2.6 info page", "http://localhost:80/%s/pkg1/2.6" % api.stagename),
        ("pkg1-2.6 docs", "http://localhost:80/%s/pkg1/2.6/+doc/index.html" % api.stagename),
        ("root/pypi", "http://localhost:80/root/pypi"),
        ("simple", "http://localhost:80/root/pypi/+simple/")]


def test_project_view(mapp, testapp):
    api = mapp.create_and_use()
    mapp.upload_file_pypi(
        "pkg1-2.6.tar.gz", b"content", "pkg1", "2.6")
    mapp.upload_file_pypi(
        "pkg1-2.7.tar.gz", b"content", "pkg1", "2.7")
    r = testapp.get(api.index + '/pkg1', headers=dict(accept="text/html"))
    assert r.status_code == 200
    links = r.html.findAll('a')
    assert [(l.text, l.attrs['href']) for l in links] == [
        ("2.7", "http://localhost:80/%s/pkg1/2.7" % api.stagename),
        ("2.6", "http://localhost:80/%s/pkg1/2.6" % api.stagename)]


def test_project_view_root_pypi(mapp, testapp):
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
    links = r.html.findAll('a')
    assert [(l.text, l.attrs['href']) for l in links] == [
        ("2.7", "http://localhost:80/root/pypi/pkg1/2.7"),
        ("2.6", "http://localhost:80/root/pypi/pkg1/2.6")]


def test_version_view(mapp, testapp):
    api = mapp.create_and_use()
    mapp.register_metadata({
        "name": "pkg1",
        "version": "2.6",
        "description": "foo"})
    mapp.upload_file_pypi(
        "pkg1-2.6.tar.gz", b"content", "pkg1", "2.6")
    mapp.upload_file_pypi(
        "pkg1-2.6.zip", b"contentzip", "pkg1", "2.6")
    content = zip_dict({"index.html": "<html/>"})
    mapp.upload_doc("pkg1.zip", content, "pkg1", "2.6", code=200)
    r = testapp.get(api.index + '/pkg1/2.6', headers=dict(accept="text/html"))
    assert r.status_code == 200
    assert r.html.find('title').text == "user1/dev/: pkg1-2.6 metadata and description"
    info = dict((t.text for t in x.findAll('td')) for x in r.html.findAll('tr'))
    assert sorted(info.keys()) == [
        'author', 'author_email', 'classifiers', 'download_url', 'home_page',
        'keywords', 'license', 'name', 'platform', 'summary', 'version']
    assert info['name'] == 'pkg1'
    assert info['version'] == '2.6'
    description = r.html.select('div.description')
    assert len(description) == 1
    description = description[0]
    assert py.builtin._totext(
        description.renderContents().strip(),
        'utf-8') == '<p>foo</p>'
    links = r.html.findAll('a')
    assert [(l.text, l.attrs['href']) for l in links] == [
        ("pkg1-2.6 docs", "http://localhost:80/%s/pkg1/2.6/+doc/index.html" % api.stagename),
        ("pkg1-2.6.tar.gz", "http://localhost:80/%s/+f/9a0364b9e99bb480dd25e1f0284c8555/pkg1-2.6.tar.gz" % api.stagename),
        ("pkg1-2.6.zip", "http://localhost:80/%s/+f/52360ae08d733016c5603d54b06b5300/pkg1-2.6.zip" % api.stagename)]


def test_version_view_root_pypi(mapp, testapp):
    pypistage = mapp.xom.model.getstage('root/pypi')
    pypistage.name2serials['pkg1'] = {}
    cache = {
        "serial": 0,
        "entrylist": ['root/pypi/+f/52360ae08d733016c5603d54b06b5300/pkg1-2.6.zip'],
        "projectname": 'pkg1'}
    pypistage.keyfs.PYPILINKS(name='pkg1').set(cache)
    r = testapp.get('/root/pypi/pkg1/2.6', headers=dict(accept="text/html"))
    assert r.status_code == 200
    links = r.html.findAll('a')
    assert [(l.text, l.attrs['href']) for l in links] == [
        ("pkg1-2.6.zip", "http://localhost:80/root/pypi/+f/None/pkg1-2.6.zip"),
        ("https://pypi.python.org/pypi/pkg1/2.6/", "https://pypi.python.org/pypi/pkg1/2.6/")]
