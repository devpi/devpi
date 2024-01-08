from devpi_common.archive import zip_dict
from devpi_common.metadata import parse_version
from devpi_server import __version__ as _devpi_server_version
from time import struct_time
import pytest
import re


devpi_server_version = parse_version(_devpi_server_version)


def compareable_text(text):
    return re.sub(r'\s+', ' ', text.strip())


def test_root_view(testapp):
    r = testapp.get('/', headers=dict(accept="text/html"))
    assert r.status_code == 200
    links = r.html.select('#content a')
    assert [(compareable_text(l.text), l.attrs['href']) for l in links] == [
        ("root", "http://localhost/root"),
        ("root/pypi PyPI", "http://localhost/root/pypi")]


def test_root_view_with_index(mapp, testapp):
    api = mapp.create_and_use()
    r = testapp.get('/', headers=dict(accept="text/html"))
    assert r.status_code == 200
    links = r.html.select('#content a')
    assert [(compareable_text(l.text), l.attrs['href']) for l in links] == [
        ("root", "http://localhost/root"),
        ("root/pypi PyPI", "http://localhost/root/pypi"),
        (api.user, "http://localhost/%s" % api.user),
        (api.stagename, "http://localhost/%s" % api.stagename)]


def test_root_view_post(testapp):
    testapp.post('/', headers=dict(accept="text/html"), code=404)


def test_user_view_root_pypi(testapp):
    r = testapp.get('/root', headers=dict(accept="text/html"))
    assert r.status_code == 200
    links = r.html.select('#content a')
    assert [(l.text.strip(), l.attrs['href']) for l in links] == [
        ("root/pypi PyPI", "http://localhost/root/pypi")]


def test_user_view(mapp, testapp):
    api = mapp.create_and_use(indexconfig=dict(bases=["root/pypi"]))
    r = testapp.get("/%s" % api.user, headers=dict(accept="text/html"))
    assert r.status_code == 200
    links = r.html.select('#content a')
    assert [(l.text.strip(), l.attrs['href']) for l in links] == [
        ("%s/dev" % api.user, "http://localhost/%s/dev" % api.user)]


def test_user_not_found(testapp):
    r = testapp.get("/blubber", headers=dict(accept="text/html"))
    assert r.status_code == 404
    content, = r.html.select('#content')
    assert "no user" in compareable_text(content.text)
    assert "blubber" in compareable_text(content.text)


def test_index_view_root_pypi(testapp):
    r = testapp.get('/root/pypi', headers=dict(accept="text/html"))
    assert r.status_code == 200
    links = r.html.select('#content a')
    assert [(l.text, l.attrs['href']) for l in links] == [
        ("simple index", "http://localhost/root/pypi/+simple/")]


def test_index_view(mapp, testapp):
    api = mapp.create_and_use(indexconfig=dict(bases=["root/pypi"]))
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
    assert 'The stage blubber/blubb could not be found.' in compareable_text(content.text)


def test_index_view_project_info(mapp, testapp):
    api = mapp.create_and_use(indexconfig=dict(bases=["root/pypi"]))
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
    api = mapp.create_and_use(indexconfig=dict(bases=["root/pypi"]))
    r = mapp.upload_file_pypi("pkg1-2.6.tar.gz", b"content", "pkg1", "2.6")
    tar_url = r.file_url
    r = testapp.xget(200, api.index, headers=dict(accept="text/html"))
    links = r.html.select('#content a')

    assert [(l.text, l.attrs['href']) for l in links] == [
        ("simple index", "http://localhost/%s/+simple/" % api.stagename),
        ("pkg1-2.6", "http://localhost/%s/pkg1/2.6" % api.stagename),
        ("pkg1-2.6.tar.gz", tar_url),
        ("root/pypi", "http://localhost/root/pypi"),
        ("simple", "http://localhost/root/pypi/+simple/")]
    zip_url = mapp.upload_file_pypi(
        "pkg1-2.6.zip", b"contentzip", "pkg1", "2.6").file_url
    r = testapp.get(api.index, headers=dict(accept="text/html"))
    assert r.status_code == 200
    links = r.html.select('#content a')
    assert [(l.text, l.attrs['href']) for l in links] == [
        ("simple index", "http://localhost/%s/+simple/" % api.stagename),
        ("pkg1-2.6", "http://localhost/%s/pkg1/2.6" % api.stagename),
        ("pkg1-2.6.tar.gz", tar_url),
        ("pkg1-2.6.zip", zip_url),
        ("root/pypi", "http://localhost/root/pypi"),
        ("simple", "http://localhost/root/pypi/+simple/")]


@pytest.mark.with_notifier
def test_index_view_project_docs(keep_docs_packed, mapp, testapp):
    api = mapp.create_and_use(indexconfig=dict(bases=["root/pypi"]))
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
    current_group = None
    grouped = {}
    for elem in elements:
        if elem.name.lower() == 'dt':
            current_group = compareable_text(elem.text)
            continue
        grouped.setdefault(current_group, []).append(
            compareable_text(elem.text))
    assert 'upload' in grouped
    assert grouped['upload'] == [
        'Users: user1', 'Groups: developers', 'Special: ANONYMOUS']


def test_title_description(mapp, testapp):
    api = mapp.create_and_use()
    mapp.modify_user(api.user, title="usertitle", description="userdescription")
    mapp.modify_index(api.stagename, indexconfig=dict(
        title="indextitle", description="indexdescription"))
    r = testapp.xget(200, '/', headers=dict(accept="text/html"))
    (content,) = r.html.select('#content')
    users = content.select('.user_index_list dt')
    assert [compareable_text(x.text) for x in users] == [
        'root', 'user1 usertitle']
    (userdescription,) = content.select('.user_index_list dd.user_description')
    assert compareable_text(userdescription.text) == "userdescription"
    links = content.select('a')
    assert [x.attrs.get('title') for x in links] == [None, None, None, 'indexdescription']
    r = testapp.xget(200, api.index, headers=dict(accept="text/html"))
    (content,) = r.html.select('#content')
    (indextitle,) = content.select('.index_title')
    assert compareable_text(indextitle.text) == "user1/dev indextitle index"
    (p,) = content.select('.index_description')
    assert compareable_text(p.text) == "indexdescription"


def test_project_view(mapp, testapp):
    api = mapp.create_and_use()
    mapp.upload_file_pypi(
        "pkg_name-2.6.tar.gz", b"content", "pkg_name", "2.6")
    mapp.upload_file_pypi(
        "pkg_name-2.6.zip", b"contentzip", "pkg_name", "2.6")
    mapp.upload_file_pypi(
        "pkg_name-2.7.tar.gz", b"content", "pkg_name", "2.7")
    r = testapp.get(api.index + '/pkg_name', headers=dict(accept="text/html"))
    assert r.status_code == 200
    links = r.html.select('#content a')
    assert [(l.text, l.attrs['href']) for l in links] == [
        ("Simple index", "http://localhost/%s/+simple/pkg-name" % api.stagename),
        ("2.7", "http://localhost/%s/pkg-name/latest" % api.stagename),
        (api.stagename, "http://localhost/%s" % api.stagename),
        ("2.7", "http://localhost/%s/pkg-name/2.7" % api.stagename),
        (api.stagename, "http://localhost/%s" % api.stagename),
        ("2.6", "http://localhost/%s/pkg-name/2.6" % api.stagename)]


def test_project_projectname_redirect(mapp, testapp):
    api = mapp.create_and_use()
    mapp.set_versiondata({
        "name": "pkg_hello", "version": "1.0"})
    mapp.upload_file_pypi(
        "pkg-hello-1.0.zip", b"123", "pkg-hello", "1.0")
    r = testapp.xget(200, api.index + '/pkg_hello', headers=dict(accept="text/html"))
    links = r.html.select('#content a')
    assert [(l.text, l.attrs['href']) for l in links] == [
        ("Simple index", "http://localhost/%s/+simple/pkg-hello" % api.stagename),
        ("1.0", "http://localhost/%s/pkg-hello/latest" % api.stagename),
        (api.stagename, "http://localhost/%s" % api.stagename),
        ("1.0", "http://localhost/%s/pkg-hello/1.0" % api.stagename)]


def test_project_not_found(mapp, testapp):
    api = mapp.create_and_use()
    r = testapp.get("/blubber/blubb/pkg1", headers=dict(accept="text/html"))
    assert r.status_code == 404
    content, = r.html.select('#content')
    assert 'The stage blubber/blubb could not be found.' in compareable_text(content.text)
    r = testapp.get(api.index + "/pkg1", headers=dict(accept="text/html"))
    assert r.status_code == 404
    content, = r.html.select('#content')
    assert 'The project pkg1 does not exist.' in compareable_text(content.text)


@pytest.mark.with_notifier
def test_project_view_docs_only(keep_docs_packed, mapp, testapp):
    api = mapp.create_and_use()
    content = zip_dict({"index.html": "<html/>"})
    mapp.set_versiondata({"name": "pkg1", "version": "2.6"})
    mapp.upload_doc(
        "pkg1.zip", content, "pkg1", "2.6", code=200, waithooks=True)
    r = testapp.xget(200, api.index + '/pkg1', headers=dict(accept="text/html"))
    (content,) = r.html.select('#content')
    assert [x.text for x in content.select('tr td')] == [
        "user1/dev", "2.6", "pkg1-2.6"]


def test_project_view_root_pypi(mapp, testapp, pypistage):
    pypistage.mock_simple("pkg1", text='''
            <a href="../../pkg/pkg1-2.7.zip" />
            <a href="../../pkg/pkg1-2.6.zip" />
        ''', pypiserial=10)
    r = testapp.get('/root/pypi/pkg1', headers=dict(accept="text/html"))
    assert r.status_code == 200
    links = r.html.select('#content a')
    assert [(l.text, l.attrs['href']) for l in links] == [
        ("Simple index", "http://localhost/%s/+simple/pkg1" % pypistage.name),
        ("PyPI page", "https://pypi.org/project/pkg1/"),
        ("2.7", "http://localhost/root/pypi/pkg1/latest"),
        ("root/pypi", "http://localhost/root/pypi"),
        ("2.7", "http://localhost/root/pypi/pkg1/2.7"),
        ("root/pypi", "http://localhost/root/pypi"),
        ("2.6", "http://localhost/root/pypi/pkg1/2.6")]


def test_project_view_root_pypi_no_releases(mapp, testapp, pypistage):
    pypistage.mock_simple("pkg1", text='', pypiserial=10)
    r = testapp.get('/root/pypi/pkg1', headers=dict(accept="text/html"))
    assert r.status_code == 200
    links = r.html.select('#content a')
    assert [(l.text, l.attrs['href']) for l in links] == [
        ("Simple index", "http://localhost/%s/+simple/pkg1" % pypistage.name),
        ("PyPI page", "https://pypi.org/project/pkg1/")]


def test_project_view_root_pypi_external_link_bad_name(mapp, testapp, pypistage):
    # root/pypi/+e/https_github.com_pypa_pip_tarball/develop
    # http://localhost:8141/root/pypi/+e/https_github.com_pypa_pip_tarball/develop#egg=pip-dev
    pypistage.mock_simple("pkg1", text='''
            <a rel="internal" href="../../pkg/pkg1-2.7.zip" />
            <a rel="internal" href="../../pkg/pkg1-2.6.zip" />
            <a href="https://github.com/pypa/pip/tarball/develop#egg=pkg1-dev" />
        ''', pypiserial=10)
    r = testapp.get('/root/pypi/pkg1', headers=dict(accept="text/html"))
    assert r.status_code == 200
    links = r.html.select('#content a')
    assert [(l.text, l.attrs['href']) for l in links] == [
        ("Simple index", "http://localhost/%s/+simple/pkg1" % pypistage.name),
        ("PyPI page", "https://pypi.org/project/pkg1/"),
        ("2.7", "http://localhost/root/pypi/pkg1/latest"),
        ("root/pypi", "http://localhost/root/pypi"),
        ("2.7", "http://localhost/root/pypi/pkg1/2.7"),
        ("root/pypi", "http://localhost/root/pypi"),
        ("2.6", "http://localhost/root/pypi/pkg1/2.6")]


@pytest.mark.with_notifier
def test_project_view_root_and_docs(keep_docs_packed, mapp, testapp, pypistage):
    pypistage.mock_simple("pkg1", text='''
            <a href="../../pkg/pkg1-2.7.zip" />
            <a href="../../pkg/pkg1-2.6.zip" />
        ''', pypiserial=10)
    api = mapp.create_and_use(indexconfig=dict(
        bases=["root/pypi"],
        mirror_whitelist=["*"]))
    content = zip_dict({"index.html": "<html/>"})
    mapp.set_versiondata({"name": "pkg1", "version": "2.6"})
    mapp.upload_doc(
        "pkg1.zip", content, "pkg1", "2.6", code=200, waithooks=True)
    r = testapp.xget(200, api.index + '/pkg1', headers=dict(accept="text/html"))
    links = r.html.select('#content a')
    assert [(l.text, l.attrs['href']) for l in links] == [
        ("Simple index", "http://localhost/%s/+simple/pkg1" % api.stagename),
        ("PyPI page", "https://pypi.org/project/pkg1/"),
        ("2.6", "http://localhost/user1/dev/pkg1/latest"),
        ("root/pypi", "http://localhost/root/pypi"),
        ("2.7", "http://localhost/root/pypi/pkg1/2.7"),
        ("root/pypi", "http://localhost/root/pypi"),
        ("2.6", "http://localhost/root/pypi/pkg1/2.6"),
        ("pkg1-2.6", "http://localhost/user1/dev/pkg1/2.6/+d/index.html")]


def test_project_view_inherited_no_versions_on_stage(mapp, testapp):
    mapp.login_root()
    mapp.create_index("prod")
    mapp.use("root/prod")
    mapp.upload_file_pypi("pkg5-1.0.tgz", b"123", "pkg5", "1.0")
    mapp.create_index("dev", indexconfig=dict(bases="root/prod"))
    mapp.use("root/dev")
    pkg_url = mapp.api.index + '/pkg5'
    testapp.xget(200, pkg_url)


@pytest.mark.with_notifier
def test_version_view(mapp, testapp, monkeypatch):
    import devpi_server.model

    # use fixed time
    def gmtime(*x):
        return struct_time((2014, 9, 15, 11, 11, 11, 0, 258, 0))

    monkeypatch.setattr('time.gmtime', gmtime)
    monkeypatch.setattr(devpi_server.model, 'gmtime', gmtime)
    api = mapp.create_and_use()
    mapp.upload_file_pypi(
        "pkg1-2.6.tar.gz", b"contentveryold", "pkg1", "2.6").file_url
    mapp.upload_file_pypi(
        "pkg1-2.6.tar.gz", b"contentold", "pkg1", "2.6").file_url
    tar3 = mapp.upload_file_pypi(
        "pkg1-2.6.tar.gz", b"content", "pkg1", "2.6").file_url
    zip = mapp.upload_file_pypi(
        "pkg1-2.6.zip", b"contentzip", "pkg1", "2.6").file_url
    content = zip_dict({"index.html": "<html/>"})
    mapp.upload_doc("pkg1.zip", content, "pkg1", "2.6", code=200)
    classifiers = ["Intended Audience :: Developers",
                   "License :: OSI Approved :: MIT License"]
    mapp.set_versiondata({
        "name": "pkg1",
        "version": "2.6",
        "author": "Foo Bear",
        "classifiers": classifiers,
        "description": u"föö".encode('utf-8')},
        waithooks=True)
    r = testapp.get(api.index + '/pkg1/2.6', headers=dict(accept="text/html"))
    assert r.status_code == 200
    assert r.html.find('title').text == "user1/dev/: pkg1-2.6 metadata and description"
    info = dict((compareable_text(t.text) for t in x.findAll('td')) for x in r.html.select('.projectinfos tr'))
    assert sorted(info.keys()) == ['author', 'classifiers']
    assert info['author'] == 'Foo Bear'
    assert info['classifiers'] == 'Intended Audience :: Developers License :: OSI Approved :: MIT License'
    description = r.html.select('#description')
    assert len(description) == 1
    description = description[0]
    assert description.renderContents().strip().decode('utf-8') == u'<p>föö</p>'
    filesinfo = [
        tuple(
            compareable_text(t.text).split()
            for t in x.findAll('td'))
        for x in r.html.select('.files tbody tr')]

    assert [x[:2] for x in filesinfo] == [
        (['pkg1-2.6.tar.gz', 'Size', '7', 'bytes', 'Type', 'Source'], []),
        (['pkg1-2.6.zip', 'Size', '10', 'bytes', 'Type', 'Source'], [])
    ]

    assert [x[-1] for x in filesinfo] == [
        [u'Replaced', u'2', u'time(s)',
         u'Uploaded', u'to', u'user1/dev', u'by', u'user1', u'2014-09-15', u'11:11:11'],
        [u'Uploaded', u'to', u'user1/dev', u'by', u'user1', u'2014-09-15', u'11:11:11']]
    links = r.html.select('#content a')
    assert [(compareable_text(l.text), l.attrs['href']) for l in links] == [
        ("Documentation", "http://localhost/%s/pkg1/2.6/+d/index.html" % api.stagename),
        ("Simple index", "http://localhost/%s/+simple/pkg1" % api.stagename),
        ("pkg1-2.6.tar.gz", tar3),
        ('user1/dev', 'http://localhost/user1/dev'),
        ("pkg1-2.6.zip", zip),
        ('user1/dev', 'http://localhost/user1/dev')]


@pytest.mark.with_notifier
def test_markdown_description_without_content_type(mapp, testapp, monkeypatch):
    api = mapp.create_and_use()
    mapp.upload_file_pypi(
        "pkg1-2.6.tar.gz", b"content", "pkg1", "2.6").file_url
    mapp.set_versiondata({
        "name": "pkg1",
        "version": "2.6",
        "author": "Foo Bear",
        "description": u'# Description'.encode('utf-8')},
        waithooks=True)
    r = testapp.get(api.index + '/pkg1/2.6', headers=dict(accept="text/html"))

    description = r.html.select('#description')
    assert len(description) == 1
    assert '#' in description[0].renderContents().strip().decode('utf-8')


@pytest.mark.with_notifier
@pytest.mark.skipif(devpi_server_version < parse_version("4.7.2dev"), reason="Needs Metadata 2.1 support")
def test_markdown_description_with_content_type(mapp, testapp, monkeypatch):
    api = mapp.create_and_use()
    mapp.upload_file_pypi(
        "pkg1-2.6.tar.gz", b"content", "pkg1", "2.6").file_url
    mapp.set_versiondata({
        "name": "pkg1",
        "version": "2.6",
        "author": "Foo Bear",
        "description": u'# Description'.encode('utf-8'),
        "description_content_type": 'text/markdown'},
        waithooks=True)
    r = testapp.get(api.index + '/pkg1/2.6', headers=dict(accept="text/html"))

    description = r.html.select('#description')
    assert len(description) == 1
    assert description[0].renderContents().strip().decode('utf-8') == u'<h1>Description</h1>'


@pytest.mark.with_notifier
def test_version_projectname(mapp, testapp):
    api = mapp.create_and_use()
    mapp.set_versiondata({
        "name": "pkg_hello", "version": "1.0", "description": "foo"})
    mapp.upload_file_pypi(
        "pkg-hello-1.0.whl", b"123", "pkg-hello", "1.0",
        register=False, waithooks=True)
    r = testapp.xget(200, api.index + "/pkg-hello/1.0", headers=dict(accept="text/html"))
    assert 'pkg-hello-1.0 metadata and description' in r.text


@pytest.mark.with_notifier
def test_description_updated(mapp, testapp):
    api = mapp.create_and_use()
    mapp.set_versiondata({
        "name": "pkg-hello", "version": "1.0", "description": "foo"})
    r = testapp.xget(200, api.index + "/pkg-hello/1.0", headers=dict(accept="text/html"))
    description, = r.html.select('#description')
    assert '<p>foo</p>' == description.renderContents().strip().decode('utf-8')
    mapp.set_versiondata({
        "name": "pkg-hello", "version": "1.0", "description": "bar"})
    r = testapp.xget(200, api.index + "/pkg-hello/1.0", headers=dict(accept="text/html"))
    description, = r.html.select('#description')
    assert '<p>bar</p>' == description.renderContents().strip().decode('utf-8')


@pytest.mark.with_notifier
def test_description_empty(mapp, testapp):
    api = mapp.create_and_use()
    mapp.set_versiondata({
        "name": "pkg-hello", "version": "1.0"})
    r = testapp.xget(200, api.index + "/pkg-hello/1.0", headers=dict(accept="text/html"))
    description, = r.html.select('#description')
    assert '<p>No description in metadata</p>' == description.renderContents().strip().decode('utf-8')


def test_version_not_found(mapp, testapp):
    api = mapp.create_and_use()
    mapp.upload_file_pypi(
        "pkg1-2.6.tar.gz", b"content", "pkg1", "2.6")
    r = testapp.get("/blubber/blubb/pkg1/2.6", headers=dict(accept="text/html"))
    assert r.status_code == 404
    content, = r.html.select('#content')
    assert 'The stage blubber/blubb could not be found.' in compareable_text(content.text)
    r = testapp.get(api.index + "/pkg2/2.6", headers=dict(accept="text/html"))
    assert r.status_code == 404
    content, = r.html.select('#content')
    assert 'The project pkg2 does not exist.' in compareable_text(content.text)
    r = testapp.get(api.index + "/pkg1/2.7", headers=dict(accept="text/html"))
    assert r.status_code == 404
    content, = r.html.select('#content')
    assert 'The version 2.7 of project pkg1 does not exist on stage' in content.text.strip()


def test_version_not_found_but_inherited_has_them(mapp, testapp):
    api1 = mapp.create_and_use(indexconfig=dict(bases=()))
    mapp.upload_file_pypi("pkg1-2.6.tar.gz", b"content", "pkg1", "2.6")
    api2 = mapp.create_and_use(indexconfig=dict(bases=(api1.stagename,)))
    testapp.xget(200, "/%s/pkg1/2.6" % api1.stagename, accept="text/html")
    testapp.xget(404, "/%s/pkg1/2.6" % api2.stagename, accept="text/html")
    testapp.xget(404, "/%s/pkg1/2.5" % api2.stagename, accept="text/html")


def test_version_view_root_pypi(mapp, testapp, pypistage):
    pypistage.mock_simple("pkg1", text='''
            <a href="../../pkg/pkg1-2.6.zip" />
        ''', pypiserial=10)
    r = testapp.xget(200, '/root/pypi/pkg1/2.6',
                     headers=dict(accept="text/html"))
    filesinfo = [tuple(compareable_text(t.text) for t in x.findAll('td')[:3]) for x in r.html.select('.files tbody tr')]
    assert filesinfo == [('pkg1-2.6.zip Type Source', '')]
    links = {l.text: l.attrs['href'] for l in r.html.select('#content a')}
    assert links["Simple index"] == "http://localhost/root/pypi/+simple/pkg1"
    assert links["pkg1-2.6.zip"].startswith("http://localhost/root/pypi/+e")
    assert "/pkg1" in links["PyPI page"]


def test_version_view_root_pypi_external_files(mapp, testapp, pypistage):
    pypistage.mock_simple(
        "pkg1", '<a href="http://example.com/releases/pkg1-2.7.zip" /a>)')
    r = testapp.get('/root/pypi/pkg1/2.7', headers=dict(accept="text/html"))
    assert r.status_code == 200
    filesinfo = [tuple(compareable_text(t.text) for t in x.findAll('td')[:3])
                 for x in r.html.select('.files tbody tr')]
    assert filesinfo == [('pkg1-2.7.zip Type Source', '')]
    silink, pypi_link, link1, link2 = list(r.html.select("#content a"))
    assert silink.text == "Simple index"
    assert silink.attrs["href"] == "http://localhost/root/pypi/+simple/pkg1"
    assert pypi_link.text == "PyPI page"
    assert "/pkg1" in pypi_link.attrs["href"]
    assert link1.text == "pkg1-2.7.zip"
    assert link1.attrs["href"].endswith("pkg1-2.7.zip")
    assert link2.text.endswith("/pkg1/2.7/")
    assert link2.attrs["href"].endswith("/pkg1/2.7/")


@pytest.mark.with_notifier
def test_version_view_description_errors(mapp, testapp):
    import textwrap
    api = mapp.create_and_use()
    description = textwrap.dedent(u"""
        Foo
        ===

            error
            -----
    """)
    mapp.set_versiondata({
        "name": "pkg1",
        "version": "2.6",
        "description": description.encode('utf-8')},
        waithooks=True)
    r = testapp.get(api.index + '/pkg1/2.6', headers=dict(accept="text/html"))
    (description,) = r.html.select('#description')
    assert "Unexpected section title" in description.text


def test_version_view_latest_stable(mapp, testapp):
    api = mapp.create_and_use()
    mapp.set_versiondata({
        "name": "pkg1",
        "version": "3.0b1"})
    mapp.set_versiondata({
        "name": "pkg1",
        "version": "2.6"})
    mapp.set_versiondata({
        "name": "pkg1",
        "version": "2.1b2"})
    mapp.set_versiondata({
        "name": "pkg1",
        "version": "2.0"})
    r = testapp.get(api.index + '/pkg1/2.0', headers=dict(accept="text/html"))
    links = r.html.select('.projectnavigation a')
    assert 'Stable version available' not in "".join(x.text for x in links)
    link = links[-1]
    assert link.text == 'Newer version available'
    assert link.attrs['href'] == api.index + '/pkg1/stable'
    r = testapp.get(api.index + '/pkg1/2.1b2', headers=dict(accept="text/html"))
    links = r.html.select('.projectnavigation a')
    assert 'Newer version available' not in "".join(x.text for x in links)
    link = links[-1]
    assert link.text == 'Stable version available'
    assert link.attrs['href'] == api.index + '/pkg1/stable'
    r = testapp.get(api.index + '/pkg1/2.6', headers=dict(accept="text/html"))
    links = r.html.select('.projectnavigation a')
    assert 'version available' not in "".join(x.text for x in links)
    r = testapp.get(api.index + '/pkg1/3.0b1', headers=dict(accept="text/html"))
    links = r.html.select('.projectnavigation a')
    assert 'Newer version available' not in "".join(x.text for x in links)
    link = links[-1]
    assert link.text == 'Stable version available'
    assert link.attrs['href'] == api.index + '/pkg1/stable'
    # test stable url
    r = testapp.get(api.index + '/pkg1/stable', headers=dict(accept="text/html"))
    assert 'pkg1-2.6 metadata and description' in r.text
    links = r.html.select('#navigation a')
    assert links[4].text == '2.6'
    assert links[4].attrs['href'] == api.index + '/pkg1/2.6'
    # test latest url
    r = testapp.get(api.index + '/pkg1/latest', headers=dict(accept="text/html"))
    assert 'pkg1-3.0b1 metadata and description' in r.text
    links = r.html.select('#navigation a')
    assert links[4].text == '3.0b1'
    assert links[4].attrs['href'] == api.index + '/pkg1/3.0b1'


def test_complex_name(mapp, testapp):
    from devpi_common import __version__
    from devpi_common.metadata import parse_version
    if parse_version(__version__) < parse_version('3.2.0dev'):
        pytest.skip("Only works with devpi-common >= 3.2.0")
    api = mapp.create_and_use()
    pkgname = "my-binary-package-name-1-4-3-yip"
    mapp.upload_file_pypi(
        "%s-0.9.tar.gz" % pkgname, b"content", pkgname, "0.9")
    r = testapp.xget(200, api.index, headers=dict(accept="text/html"))
    links = r.html.select('#content a')
    assert [(compareable_text(l.text), l.attrs['href']) for l in links] == [
        ('simple index', 'http://localhost/user1/dev/+simple/'),
        ('%s-0.9' % pkgname, 'http://localhost/user1/dev/%s/0.9' % pkgname),
        (
            '%s-0.9.tar.gz' % pkgname,
            'http://localhost/user1/dev/+f/ed7/002b439e9ac84/%s-0.9.tar.gz#sha256=ed7002b439e9ac845f22357d822bac1444730fbdb6016d3ec9432297b9ec9f73' % pkgname)]
    r = testapp.xget(
        200, api.index + '/%s' % pkgname, headers=dict(accept="text/html"))
    links = r.html.select('#content a')
    assert [(compareable_text(l.text), l.attrs['href']) for l in links] == [
        ("Simple index", "http://localhost/%s/+simple/%s" % (api.stagename, pkgname)),
        ('0.9', 'http://localhost/user1/dev/%s/latest' % pkgname),
        ('user1/dev', 'http://localhost/user1/dev'),
        ('0.9', 'http://localhost/user1/dev/%s/0.9' % pkgname)]


@pytest.mark.with_notifier
def test_whitelist(mapp, pypistage, testapp):
    pypistage.mock_simple(
        "pkg1", '<a href="http://example.com/releases/pkg1-2.7.zip" /a>)')
    api = mapp.create_and_use(indexconfig=dict(bases=["root/pypi"]))
    mapp.set_versiondata(
        {"name": "pkg1", "version": "2.6", "description": "foo"},
        set_whitelist=False)
    mapp.upload_file_pypi(
        "pkg1-2.6.tgz", b"123", "pkg1", "2.6", code=200,
        waithooks=True, set_whitelist=False)
    # version view
    r = testapp.get('%s/pkg1/2.6' % api.index, accept="text/html")
    (infonote,) = r.html.select('.infonote')
    text = compareable_text(infonote.text)
    assert text == "Because this project isn't in the mirror_whitelist, no releases from root/pypi are included."
    # project view
    r = testapp.get('%s/pkg1' % api.index, accept="text/html")
    (infonote,) = r.html.select('.infonote')
    text = compareable_text(infonote.text)
    assert text == "Because this project isn't in the mirror_whitelist, no releases from root/pypi are included."
    # index view
    r = testapp.get(api.index, accept="text/html")
    assert "No packages whitelisted." in r.unicode_body
    # now set the whitelist
    mapp.upload_file_pypi(
        "pkg1-2.8.tgz", b"123", "pkg1", "2.8", code=200,
        waithooks=True, set_whitelist=True)
    # version view
    r = testapp.get('%s/pkg1/2.8' % api.index, accept="text/html")
    assert r.html.select('.infonote') == []
    # project view
    r = testapp.get('%s/pkg1' % api.index, accept="text/html")
    assert r.html.select('.infonote') == []
    # index view
    r = testapp.get(api.index, accept="text/html")
    (whitelist,) = r.html.select('.whitelist')
    text = compareable_text(whitelist.text)
    assert text == "pkg1"
