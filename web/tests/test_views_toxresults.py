import hashlib
import json
import pytest
import re


def compareable_text(text):
    return re.sub(r'\s+', ' ', text.strip())


@pytest.mark.with_notifier
def test_testdata(mapp, testapp, tox_result_data):
    api = mapp.create_and_use()
    mapp.set_versiondata(
        {"name": "pkg1", "version": "2.6", "description": "foo"})
    mapp.upload_file_pypi(
        "pkg1-2.6.tgz", b"123", "pkg1", "2.6", code=200, waithooks=True)
    path, = mapp.get_release_paths("pkg1")
    r = testapp.post(path, json.dumps(tox_result_data))
    assert r.status_code == 200
    r = testapp.post(path, json.dumps({"testenvs": {"py27": {}}}))
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
    content = "\n".join([compareable_text(x.text) for x in r.html.select('.toxresult')])
    assert "No setup performed" in content
    assert "everything fine" in content
    r = testapp.xget(200, links[1].attrs['href'])
    (row,) = [
        tuple(
            compareable_text(t.text) if len(t.text.split()) < 2 else " ".join(t.text.split())
            for t in x.findAll('td'))
        for x in r.html.select('tbody tr')]
    assert row[0].startswith("pkg1-2.6.tgz.toxresult")
    assert row[1:] == ("foo", "linux2", "py27", "", "No setup performed Tests")


@pytest.mark.with_notifier
def test_testdata_notfound(mapp, testapp):
    # make sure we have a user, index and package
    mapp.create_and_use()
    mapp.set_versiondata(
        {"name": "pkg1", "version": "2.6", "description": "foo"})
    # now get toxresults for another version
    r = testapp.xget(
        404,
        '/user1/dev/pkg1/2.7/+toxresults/pkg1-2.7.tgz',
        headers=dict(accept="text/html"))
    assert 'pkg1-2.7 is not registered' in r.text


@pytest.mark.with_notifier
def test_testdata_corrupt(mapp, testapp):
    api = mapp.create_and_use()
    mapp.set_versiondata(
        {"name": "pkg1", "version": "2.6", "description": "foo"})
    mapp.upload_file_pypi(
        "pkg1-2.6.tgz", b"123", "pkg1", "2.6", code=200,
        waithooks=True)
    path, = mapp.get_release_paths("pkg1")
    r = testapp.post(path, json.dumps({"testenvs": {"py27": {}}}))
    assert r.status_code == 200
    testapp.xget(200, api.index, headers=dict(accept="text/html"))


@pytest.mark.with_notifier
def test_testdata_missing(mapp, testapp, tox_result_data):
    api = mapp.create_and_use()
    mapp.set_versiondata(
        {"name": "pkg1", "version": "2.6", "description": "foo"})
    mapp.upload_file_pypi(
        "pkg1-2.6.tgz", b"123", "pkg1", "2.6", code=200,
        waithooks=True)
    path, = mapp.get_release_paths("pkg1")
    r = testapp.post(path, json.dumps(tox_result_data))
    assert r.status_code == 200
    with mapp.xom.model.keyfs.transaction(write=True):
        stage = mapp.xom.model.getstage(api.stagename)
        link, = stage.get_releaselinks('pkg1')
        linkstore = stage.get_linkstore_perstage(link.project, link.version)
        toxresult_link, = linkstore.get_links(rel="toxresult", for_entrypath=link)
        # delete the tox result file
        toxresult_link.entry.file_delete()
    r = testapp.xget(200, api.index, headers=dict(accept="text/html"))
    assert '.toxresult' not in r.unicode_body


@pytest.mark.with_notifier
def test_testdata_latest_version(mapp, testapp, tox_result_data):
    api = mapp.create_and_use()
    mapp.set_versiondata(
        {"name": "pkg1", "version": "2.6", "description": "foo"})
    mapp.upload_file_pypi(
        "pkg1-2.6.tgz", b"123", "pkg1", "2.6", code=200,
        waithooks=True)
    path, = mapp.get_release_paths("pkg1")
    r = testapp.post(path, json.dumps(tox_result_data))
    assert r.status_code == 200
    r = testapp.xget(200, api.index + '/pkg1/latest', headers=dict(accept="text/html"))
    links = r.html.select('td.toxresults a')
    assert len(links) == 2
    assert links[0].attrs['href'].startswith(api.index + '/pkg1/2.6')
    assert links[1].attrs['href'].startswith(api.index + '/pkg1/2.6')


def test_toxresults_state():
    from devpi_web.views import get_toxresults_info
    from devpi_web.views import get_toxresults_state

    class LinkStore(list):
        def get_links(self, rel, for_entrypath):
            return self[for_entrypath]

    class Link(object):
        def __init__(self, testenvs):
            self.testenvs = testenvs
            self.basename = "pytest-1.7.zip.toxresult"

        @property
        def entry(self):
            return self

        def file_get_content(self):
            result = {
                "reportversion": "1",
                "toxversion": "1.6",
                "platform": "linux2",
                "host": "foo",
                "installpkg": {
                    "basename": "pytest-1.7.zip",
                    "md5": hashlib.md5(b"123").hexdigest(),
                    "sha256": hashlib.sha256(b"123").hexdigest(),
                },
                "testenvs": self.testenvs}
            return json.dumps(result).encode('utf-8')

    linkstore = LinkStore([[Link({})]])
    assert get_toxresults_state(get_toxresults_info(linkstore, 0)) is None

    linkstore = LinkStore([[Link({"py27": {}})]])
    assert get_toxresults_state(get_toxresults_info(linkstore, 0)) == 'unknown'

    linkstore = LinkStore([[Link({"py27": {"test": []}})]])
    assert get_toxresults_state(get_toxresults_info(linkstore, 0)) == 'unknown'

    linkstore = LinkStore([[Link({"py27": {"test": [{"command": ["python"]}]}})]])
    assert get_toxresults_state(get_toxresults_info(linkstore, 0)) is None

    linkstore = LinkStore([[Link({"py27": {
        "test": [{"command": ["python"], "retcode": 0, "output": "OK"}]}})]])
    assert get_toxresults_state(get_toxresults_info(linkstore, 0)) == 'passed'

    linkstore = LinkStore([[Link({"py27": {
        "test": [{"command": ["python"], "retcode": 1, "output": "NOTOK"}]}})]])
    assert get_toxresults_state(get_toxresults_info(linkstore, 0)) == 'failed'

    linkstore = LinkStore([[Link({"py27": {
        "setup": [],
        "test": [{"command": ["python"], "retcode": 0, "output": "OK"}]}})]])
    assert get_toxresults_state(get_toxresults_info(linkstore, 0)) == 'passed'

    linkstore = LinkStore([[Link({"py27": {
        "setup": [],
        "test": [{"command": ["python"], "retcode": 1, "output": "NOTOK"}]}})]])
    assert get_toxresults_state(get_toxresults_info(linkstore, 0)) == 'failed'

    linkstore = LinkStore([[Link({"py27": {
        "setup": [{"command": ["python"], "retcode": 0, "output": "OK"}],
        "test": []}})]])
    assert get_toxresults_state(get_toxresults_info(linkstore, 0)) == 'unknown'

    linkstore = LinkStore([[
        Link({"py34": {
            "setup": [],
            "test": [{"command": ["python"], "retcode": 0, "output": "OK"}]}}),
        Link({"py27": {
            "setup": [],
            "test": [{"command": ["python"], "retcode": 0, "output": "OK"}]}})]])
    assert get_toxresults_state(get_toxresults_info(linkstore, 0)) == 'passed'

    linkstore = LinkStore([[
        Link({"py34": {
            "setup": [],
            "test": [{"command": ["python"], "retcode": 0, "output": "OK"}]}}),
        Link({"py27": {
            "setup": [],
            "test": [{"command": ["python"], "retcode": 1, "output": "NOTOK"}]}})]])
    assert get_toxresults_state(get_toxresults_info(linkstore, 0)) == 'failed'

    linkstore = LinkStore([[
        Link({"py34": {
            "setup": [],
            "test": [{"command": ["python"], "retcode": 0, "output": "OK"}]}}),
        Link({"py27": {
            "setup": [{"command": ["python"], "retcode": 0, "output": "OK"}],
            "test": []}})]])
    assert get_toxresults_state(get_toxresults_info(linkstore, 0)) == 'unknown'

    linkstore = LinkStore([[Link({
        "py34": {
            "setup": [],
            "test": [{"command": ["python"], "retcode": 0, "output": "OK"}]},
        "py27": {
            "setup": [],
            "test": [{"command": ["python"], "retcode": 0, "output": "OK"}]}})]])
    assert get_toxresults_state(get_toxresults_info(linkstore, 0)) == 'passed'

    linkstore = LinkStore([[Link({
        "py34": {
            "setup": [],
            "test": [{"command": ["python"], "retcode": 0, "output": "OK"}]},
        "py27": {
            "setup": [],
            "test": [{"command": ["python"], "retcode": 1, "output": "NOTOK"}]}})]])
    assert get_toxresults_state(get_toxresults_info(linkstore, 0)) == 'failed'

    linkstore = LinkStore([[Link({
        "py34": {
            "setup": [],
            "test": [{"command": ["python"], "retcode": 0, "output": "OK"}]},
        "py27": {
            "setup": [{"command": ["python"], "retcode": 0, "output": "OK"}],
            "test": []}})]])
    assert get_toxresults_state(get_toxresults_info(linkstore, 0)) == 'unknown'
