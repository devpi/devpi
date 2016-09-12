# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import hashlib
import pytest
import py
import json
import posixpath
from bs4 import BeautifulSoup

from pyramid.response import Response
from devpi_common.metadata import splitbasename
from devpi_common.url import URL
from devpi_common.archive import Archive, zip_dict
from devpi_common.viewhelp import ViewLinkStore

import devpi_server.views
from devpi_server.views import tween_keyfs_transaction, make_uuid_headers
from devpi_server.extpypi import parse_index

from .functional import TestUserThings, TestIndexThings  # noqa
from .functional import TestMirrorIndexThings  # noqa

import devpi_server.filestore
from devpi_server.filestore import get_default_hash_spec, make_splitdir

proj = pytest.mark.parametrize("proj", [True, False])
pytestmark = [pytest.mark.notransaction]

def getfirstlink(text):
    return BeautifulSoup(text).findAll("a")[0]

def hash_spec_matches(hash_spec, content):
    hash_type, hash_value = hash_spec.split("=")
    digest = getattr(hashlib, hash_type)(content).hexdigest()
    return digest == hash_value


@pytest.mark.parametrize("kind", ["user", "index"])
@pytest.mark.parametrize("name,status", [
    ("foo_bar", 'ok'),
    ("foo-bar", 'ok'),
    ("foo.bar", 'ok'),
    ("foo.bar42", 'ok'),
    ("foo@bar42", 'ok'),
    ("foo:bar42", 'fatal'),
    ("foo!bar42", 'fatal'),
    ("foo~bar42", 'fatal'),
    (":foobar", 'fatal'),
    (":foobar:", 'fatal')])
def test_invalid_name(caplog, testapp, name, status, kind):
    reqdict = dict(password="123")
    if kind == "user":
        r = testapp.put_json("/%s" % name, reqdict, expect_errors=True)
    else:
        r = testapp.put_json("/foo", reqdict)
        testapp.set_auth("foo", "123")
        r = testapp.put_json("/foo/%s" % name, {}, expect_errors=True)
    if status in ('ok', 'warn'):
        if kind == "user":
            code = 201
        else:
            code = 200
    else:
        code = 400
    assert r.status_code == code
    if status == 'fatal':
        msg = (
            "%sname '%s' contains characters that aren't allowed. "
            "Any ascii symbol besides -.@_ is blocked." % (kind, name))
        assert r.json['message'] == msg


def test_user_patch_keeps_missing_keys(testapp):
    # needed for devpi-client < 2.5.0
    testapp.put_json("/foo", dict(password="123"))
    testapp.set_auth('foo', '123')
    r = testapp.get("/foo")
    assert r.json['result'] == {'username': 'foo', 'indexes': {}}
    testapp.patch_json("/foo", dict(title="foo"))
    r = testapp.get("/foo")
    assert r.json['result'] == {
        'username': 'foo', 'title': 'foo', 'indexes': {}}
    testapp.patch_json("/foo", dict(description="bar"))
    r = testapp.get("/foo")
    assert r.json['result'] == {
        'username': 'foo', 'title': 'foo', 'description': 'bar', 'indexes': {}}
    testapp.patch_json("/foo", dict(description=""))
    r = testapp.get("/foo")
    assert r.json['result'] == {
        'username': 'foo', 'title': 'foo', 'indexes': {}}


@pytest.mark.parametrize("nodeinfo,expected", [
    ({}, (None, None)),
    ({"uuid": "123", "role":"master"}, ("123", "123")),
    ({"uuid": "123", "role":"replica"}, ("123", "")),
    ({"uuid": "123", "master-uuid": "456", "role":"replica"}, ("123", "456")),
])
def test_make_uuid_headers(nodeinfo, expected):
    output = make_uuid_headers(nodeinfo)
    assert output == expected

def test_simple_project(pypistage, testapp):
    name = "qpwoei"
    r = testapp.get("/root/pypi/+simple/" + name)
    assert r.status_code == 404
    assert r.headers["X-DEVPI-SERIAL"]
    # easy_install fails if the result isn't html
    assert "html" in r.headers['content-type']
    assert not parse_index("http://localhost", r.text, scrape=False).releaselinks

    path = "/%s-1.0.zip" % name
    pypistage.mock_simple(name, text='<a href="%s"/>' % path)
    r = testapp.get("/root/pypi/+simple/%s" % name)
    assert r.status_code == 200
    links = BeautifulSoup(r.text).findAll("a")
    assert len(links) == 1
    assert links[0].get("href").endswith(path)

@pytest.mark.parametrize("outside_url", ['', 'http://localhost/devpi'])
def test_simple_project_outside_url_subpath(mapp, outside_url, pypistage, testapp):
    api = mapp.create_and_use(indexconfig=dict(bases=["root/pypi"]))
    mapp.upload_file_pypi(
        "qpwoei-1.0.tar.gz", b'123', "qpwoei", "1.0", indexname=api.stagename)
    pypistage.mock_simple("qpwoei", text='<a href="/qpwoei-1.0.zip"/>')
    headers={str('X-outside-url'): str(outside_url)}
    r = testapp.get("/%s/+simple/qpwoei" % api.stagename, headers=headers)
    assert r.status_code == 200
    links = sorted(x["href"] for x in BeautifulSoup(r.text).findAll("a"))
    assert len(links) == 2
    hash_spec = get_default_hash_spec(b'123')
    hashdir = "/".join(make_splitdir(hash_spec))
    assert links == [
        '../+f/%s/qpwoei-1.0.tar.gz#%s' % (hashdir, hash_spec),
        '../../../root/pypi/+e/https_pypi.python.org/qpwoei-1.0.zip']
    testapp.xget(
        200, URL("/%s/+simple/qpwoei" % api.stagename).joinpath(links[0]).path,
        headers=headers)


@pytest.mark.parametrize(
    "user_agent",
    [
        'pip/1.4.1',
        'setuptools/6.1',
        'Python-urllib/3.5 setuptools/6.1',
        'setuptools/6.1 Python-urllib/3.5',
        'pex/1.0.1',
        'pip/6.0.dev1 {"cpu":"x86_64","distro":{"name":"OS X","version":"10.9.5"},"implementation":{"name":"CPython","version":"2.7.8"},"installer":{"name":"pip","version":"6.0.dev1"},"python":"2.7.8","system":{"name":"Darwin","release":"13.4.0"}}'],
    ids=['pip', 'setuptools', 'urllib-setuptools', 'setuptools-urllib', 'pex', 'pip6'])
def test_project_redirect(pypistage, testapp, user_agent):
    name = "qpwoei"
    headers = {'User-Agent': str(user_agent), "Accept": str("text/html")}

    r = testapp.get("/root/pypi/%s" % name, headers=headers, follow=False)
    assert r.status_code == 302
    assert r.headers["location"].endswith("/root/pypi/+simple/%s" % name)
    # trailing slash will redirect to non trailing slash first
    r = testapp.get("/root/pypi/%s/" % name, headers=headers, follow=False)
    assert r.status_code == 302
    assert r.headers["location"].endswith("/root/pypi/+simple/%s" % name)

def test_simple_project_unicode_rejected(pypistage, testapp, dummyrequest):
    from devpi_server.view_auth import RootFactory
    from devpi_server.views import PyPIView
    from pyramid.httpexceptions import HTTPClientError
    dummyrequest.registry['xom'] = testapp.xom
    dummyrequest.log = pypistage.xom.log
    dummyrequest.context = RootFactory(dummyrequest)
    view = PyPIView(dummyrequest)
    project = py.builtin._totext(b"qpw\xc3\xb6", "utf-8")
    dummyrequest.matchdict.update(user="x", index="y", project=project)
    with pytest.raises(HTTPClientError):
        view.simple_list_project()

def test_simple_url_longer_triggers_404(testapp):
    assert testapp.get("/root/pypi/+simple/pytest/1.0/").status_code == 404
    assert testapp.get("/root/pypi/+simple/pytest/1.0").status_code == 404

def test_simple_project_pypi_egg(pypistage, testapp):
    pypistage.mock_simple("py",
        """<a href="http://bb.org/download/py.zip#egg=py-dev" />""")
    r = testapp.get("/root/pypi/+simple/py")
    assert r.status_code == 200
    links = BeautifulSoup(r.text).findAll("a")
    assert len(links) == 1
    r = testapp.get("/root/pypi")
    assert r.status_code == 200

@pytest.mark.nomockprojectsremote
def test_simple_list(pypistage, testapp):
    pypistage.mock_simple_projects(["hello1", "hello2"])
    pypistage.mock_simple("hello1", "<html/>")
    pypistage.mock_simple("hello2", "<html/>")
    r = testapp.get("/root/pypi/+simple/hello1", expect_errors=False)
    serial = int(r.headers["X-DEVPI-SERIAL"])
    r2 = testapp.get("/root/pypi/+simple/hello2", expect_errors=False)
    assert int(r2.headers["X-DEVPI-SERIAL"]) == serial + 1

    r = testapp.get("/root/pypi/+simple/hello3")
    assert r.status_code == 404
    # easy_install fails if the result isn't html
    assert "html" in r.headers['content-type']

    # get the full projects page and see what is in
    r = testapp.get("/root/pypi/+simple/")
    assert r.status_code == 200
    links = BeautifulSoup(r.text, "html.parser").findAll("a")
    assert len(links) == 2
    hrefs = [a.get("href") for a in links]
    assert hrefs == ["hello1", "hello2"]

def test_correct_resolution_order(pypistage, mapp, testapp):
    pypistage.mock_simple("hello", pkgver="hello-1.0.tar.gz")
    index1 = mapp.create_and_use()
    index2 = mapp.create_and_use(indexconfig=dict(bases=[index1.stagename]))
    index3 = mapp.create_and_use(
        indexconfig=dict(bases=[index2.stagename, 'root/pypi']))
    mapp.use(index1.stagename)
    mapp.login(index1.user, index1.password)
    mapp.upload_file_pypi("hello-1.0.tar.gz", b'123', "hello", "1.0",
                          indexname=index1.stagename)
    # the package should be found in our internal index, not on root/pypi
    r = testapp.get("/%s/+simple/hello" % index3.stagename)
    assert index1.stagename in r.text

def test_simple_page_pypi_serial(pypistage, testapp):
    pypistage.mock_simple("hello1", text="qwe", pypiserial=None)
    r = testapp.get("/root/pypi/+simple/hello1", expect_errors=False)
    assert "X-PYPI-LAST-SERIAL" not in r.headers
    pypistage.mock_simple("hello2", pkgver="hello2-1.0.zip")
    r = testapp.get("/root/pypi/+simple/hello2", expect_errors=False)
    assert r.headers.get("X-PYPI-LAST-SERIAL") == '10000'
    assert '/hello2-1.0.zip">hello2-1.0.zip</a>' in r.unicode_body

def test_simple_refresh(mapp, model, pypistage, testapp):
    pypistage.mock_simple("hello", "<html/>")
    r = testapp.xget(200, "/root/pypi/+simple/hello")
    input, = r.html.select('form input')
    assert input.attrs['name'] == 'refresh'
    assert input.attrs['value'] == 'Refresh'
    with model.keyfs.transaction(write=False):
        info = pypistage.key_projsimplelinks("hello").get()
    assert info != {}
    r = testapp.post("/root/pypi/+simple/hello/refresh")
    assert r.status_code == 302
    assert r.location.endswith("/root/pypi/+simple/hello")
    with model.keyfs.transaction(write=False):
        info = pypistage.key_projsimplelinks("hello").get()
    assert info["links"] == []

def test_inheritance_versiondata(mapp, model):
    api1 = mapp.create_and_use()
    mapp.upload_file_pypi("package-1.0.tar.gz", b'123',
                          "package", "1.0", indexname=api1.stagename)
    api2 = mapp.create_and_use(indexconfig={"bases": (api1.stagename,)})
    r = mapp.getjson(api2.index + "/package")
    assert len(r["result"]) == 1


@pytest.mark.parametrize("project", ["pkg", "pkg-some"])
@pytest.mark.parametrize("stagename", [None, "root/pypi"])
def test_simple_refresh_inherited(mapp, model, pypistage, testapp, project,
                                  stagename):
    pypistage.mock_simple(project, '<a href="/%s-1.0.zip" />' % project,
                          serial=100)
    if stagename is None:
        api = mapp.create_and_use(indexconfig=dict(bases=["root/pypi"]))
    else:
        api = mapp.use(stagename)
    stagename = api.stagename

    r = testapp.xget(200, "/%s/+simple/%s" % (stagename, project))
    input, = r.html.select('form input')
    assert input.attrs['name'] == 'refresh'
    #assert input.attrs['value'] == 'Refresh PyPI links'
    with model.keyfs.transaction(write=False):
        info = pypistage.key_projsimplelinks(project).get()
    assert info != {}
    pypistage.mock_simple(project, '<a href="/%s-2.0.zip" />' % project,
                          serial=200)
    r = testapp.post("/%s/+simple/%s/refresh" % (stagename, project))
    assert r.status_code == 302
    assert r.location.endswith("/%s/+simple/%s" % (stagename, project))
    with model.keyfs.transaction(write=False):
        info = pypistage.key_projsimplelinks(project).get()
    elist = info["links"]
    assert len(elist) == 1
    assert elist[0][0].endswith("-2.0.zip")


def test_simple_refresh_inherited_not_whitelisted(mapp, testapp):
    api = mapp.create_and_use()
    mapp.set_versiondata(dict(name="pkg", version="1.0"), set_whitelist=False)
    r = testapp.xget(200, "/%s/+simple/pkg" % api.stagename)
    assert len(r.html.select('form')) == 0


def test_simple_blocked_warning(mapp, pypistage, testapp):
    pypistage.mock_simple('pkg', '<a href="/pkg-1.0.zip" />', serial=100)
    api = mapp.create_and_use(indexconfig=dict(bases=["root/pypi"]))
    mapp.set_versiondata(dict(name="pkg", version="1.0"), set_whitelist=False)
    r = testapp.xget(200, "/%s/+simple/pkg" % api.stagename)
    (paragraph,) = r.html.select('p')
    assert paragraph.text == "INFO: Because this project isn't in the mirror_whitelist, no releases from root/pypi are included."
    mapp.set_versiondata(dict(name="pkg", version="1.1"), set_whitelist=True)
    r = testapp.xget(200, "/%s/+simple/pkg" % api.stagename)
    assert r.html.select('p') == []


def test_indexroot(testapp, model):
    with model.keyfs.transaction(write=True):
        user = model.create_user("user", "123")
        user.create_stage("index", bases=("root/pypi",))
    r = testapp.get("/user/index")
    assert r.status_code == 200

def test_indexroot_root_pypi(testapp, xom):
    r = testapp.get("/root/pypi")
    assert r.status_code == 200
    assert b"in-stage" not in r.body

@pytest.mark.parametrize("url", [
    '/root/pypi/{name}',
    '/root/pypi/{name}/2.6',
    '/root/pypi/+simple/{name}',
])
@pytest.mark.parametrize("code", [-1, 500, 501, 502, 503])
def test_upstream_not_reachable(reqmock, pypistage, testapp, code, url):
    name = "whatever{code}".format(code=code+100)
    pypistage.mock_simple(name, '', status_code=code)
    r = testapp.get(url.format(name=name), accept="application/json")
    assert r.status_code == 502


def test_upstream_not_reachable_but_cache_still_returned(pypistage, mapp, testapp, monkeypatch):
    index_name = 'user/name'
    name = 'pkg1'
    version = '1.0'
    mapp.create_and_use(index_name, indexconfig=dict(bases=["root/pypi"]))
    mapp.upload_file_pypi(
        '{name}-{version}.tgz'.format(name=name, version=version),
        b'123',
        name=name,
        version=version,
        indexname=index_name,
        register=True)
    # first we check what happens if the cache is empty
    pypistage.mock_simple(name, '', status_code=502)
    r = testapp.get('/{index_name}/{name}'.format(index_name=index_name, name=name), accept="application/json")
    assert r.status_code == 200
    assert set(r.json['result']) == set(['1.0'])
    # then we simulate that the mirror is available to fill the cache
    pypistage.mock_simple(name, '<a href="/%s-1.1.zip" />' % name)
    r = testapp.get('/{index_name}/{name}'.format(index_name=index_name, name=name), accept="application/json")
    assert r.status_code == 200
    assert set(r.json['result']) == set(['1.0', '1.1'])
    # and check once more with the filled cache
    pypistage.mock_simple(name, '', status_code=502)
    r = testapp.get('/{index_name}/{name}'.format(index_name=index_name, name=name), accept="application/json")
    assert r.status_code == 200
    assert set(r.json['result']) == set(['1.0', '1.1'])


def test_pkgserv(httpget, pypistage, testapp):
    pypistage.mock_simple("package", '<a href="/package-1.0.zip" />')
    pypistage.mock_extfile("/package-1.0.zip", b"123")
    r = testapp.get("/root/pypi/+simple/package")
    assert r.status_code == 200
    href = getfirstlink(r.text).get("href")
    assert not posixpath.isabs(href)
    url = URL(r.request.url).joinpath(href).url
    r = testapp.get(url)
    assert r.body == b"123"

def test_pkgserv_remote_failure(httpget, pypistage, testapp):
    pypistage.mock_simple("package", '<a href="/package-1.0.zip" />')
    r = testapp.get("/root/pypi/+simple/package")
    assert r.status_code == 200
    href = getfirstlink(r.text).get("href")
    url = URL(r.request.url).joinpath(href).url
    pypistage.mock_extfile("/package-1.0.zip", b"123", status_code=500)
    r = testapp.get(url)
    assert r.status_code == 502

def test_apiconfig(testapp):
    r = testapp.get_json("/user/name/+api", status=404)
    assert r.status_code == 404
    r = testapp.get_json("/root/pypi/+api")
    assert r.status_code == 200
    assert not "pypisubmit" in r.json["result"]

class TestStatus:
    def test_status_master(self, testapp):
        r = testapp.get_json("/+status", status=200)
        assert r.status_code == 200
        data = r.json["result"]
        assert data["role"] == "MASTER"

    def test_status_replica(self, maketestapp, replica_xom):
        testapp = maketestapp(replica_xom)
        r = testapp.get_json("/+status", status=200)
        assert r.status_code == 200
        data = r.json["result"]
        assert data["role"] == "REPLICA"
        assert data["serial"] == replica_xom.keyfs.get_current_serial()
        assert data["replication-errors"] == {}


class TestStatusInfoPlugin:
    @pytest.fixture
    def plugin(self):
        from devpi_server.views import devpiweb_get_status_info
        return devpiweb_get_status_info

    def _xomrequest(self, xom):
        from pyramid.request import Request
        request = Request.blank("/blankpath")
        request.registry = dict(
            xom=xom,
            devpi_version_info=[])
        return request

    @pytest.mark.with_notifier
    def test_no_issue(self, plugin, xom):
        request = self._xomrequest(xom)
        serial = xom.keyfs.get_current_serial()
        xom.keyfs.notifier.wait_event_serial(serial)
        # if devpi-web is installed make sure we look again
        # at the serial in case a hook created a new serial
        serial = xom.keyfs.get_current_serial()
        xom.keyfs.notifier.wait_event_serial(serial)
        result = plugin(request)
        assert not xom.is_replica()
        assert result == []

    @pytest.mark.xfail(reason="sometimes fail due to race condition in db table creation")
    @pytest.mark.with_replica_thread
    @pytest.mark.with_notifier
    def test_no_issue_replica(self, plugin, xom):
        request = self._xomrequest(xom)
        serial = xom.keyfs.get_current_serial()
        xom.keyfs.notifier.wait_event_serial(serial)
        result = plugin(request)
        assert hasattr(xom, 'replica_thread')
        assert xom.is_replica()
        assert result == []

    def test_events_lagging(self, plugin, xom, monkeypatch):
        # write transaction so event processing can lag behind
        with xom.keyfs.transaction(write=True):
            xom.model.create_user("hello", "pass")

        import time
        now = time.time()
        request = self._xomrequest(xom)
        # nothing if events never processed directly after startup
        monkeypatch.setattr(devpi_server.views, "time", lambda: now + 30)
        result = plugin(request)
        assert result == []
        # fatal after 5 minutes
        monkeypatch.setattr(devpi_server.views, "time", lambda: now + 310)
        result = plugin(request)
        assert result == [dict(
            status='fatal',
            msg="The event processing doesn't seem to start")]
        # fake first event processed
        xom.keyfs.notifier.write_event_serial(0)
        xom.keyfs.notifier.event_serial_in_sync_at = now
        # no report in the first minute
        monkeypatch.setattr(devpi_server.views, "time", lambda: now + 30)
        result = plugin(request)
        assert result == []
        # warning after 5 minutes
        monkeypatch.setattr(devpi_server.views, "time", lambda: now + 310)
        result = plugin(request)
        assert result == [dict(
            status='warn',
            msg='No changes processed by plugins for more than 5 minutes')]
        # fatal after 30 minutes
        monkeypatch.setattr(devpi_server.views, "time", lambda: now + 1810)
        result = plugin(request)
        assert result == [dict(
            status='fatal',
            msg='No changes processed by plugins for more than 30 minutes')]
        # warning about sync after one hour
        monkeypatch.setattr(devpi_server.views, "time", lambda: now + 3610)
        result = plugin(request)
        assert result == [
            dict(
                status='warn',
                msg="The event processing hasn't been in sync for more than 1 hour"),
            dict(
                status='fatal',
                msg='No changes processed by plugins for more than 30 minutes')]
        # fatal sync state after 6 hours
        monkeypatch.setattr(devpi_server.views, "time", lambda: now + 21610)
        result = plugin(request)
        assert result == [
            dict(
                status='fatal',
                msg="The event processing hasn't been in sync for more than 6 hours"),
            dict(
                status='fatal',
                msg='No changes processed by plugins for more than 30 minutes')]

    def test_replica_lagging(self, plugin, makexom, monkeypatch):
        from devpi_server.replica import ReplicaThread
        import time
        now = time.time()
        xom = makexom(["--master=http://localhost"])
        request = self._xomrequest(xom)
        xom.replica_thread = ReplicaThread(xom)
        assert xom.is_replica()
        # fake first serial processed
        xom.replica_thread.update_master_serial(0)
        xom.replica_thread.replica_in_sync_at = now
        # no report in the first minute
        result = plugin(request)
        assert result == []
        # warning after one minute
        monkeypatch.setattr(devpi_server.views, "time", lambda: now + 70)
        result = plugin(request)
        assert result == [dict(
            status='warn',
            msg='Replica is behind master for more than 1 minute')]
        # fatal after five minutes
        monkeypatch.setattr(devpi_server.views, "time", lambda: now + 310)
        result = plugin(request)
        assert result == [dict(
            status='fatal',
            msg='Replica is behind master for more than 5 minutes')]

    def test_initial_master_connection(self, plugin, makexom, monkeypatch):
        from devpi_server.replica import ReplicaThread
        import time
        now = time.time()
        xom = makexom(["--master=http://localhost"])
        request = self._xomrequest(xom)
        xom.replica_thread = ReplicaThread(xom)
        assert xom.is_replica()
        assert xom.replica_thread.started_at is None
        # fake replica start
        xom.replica_thread.started_at = now
        # no report in the first minute
        result = plugin(request)
        assert result == []
        # warning after one minute
        monkeypatch.setattr(devpi_server.views, "time", lambda: now + 70)
        result = plugin(request)
        assert result == [dict(
            status='warn',
            msg='No contact to master for more than 1 minute')]
        # fatal after five minutes
        monkeypatch.setattr(devpi_server.views, "time", lambda: now + 310)
        result = plugin(request)
        assert result == [dict(
            status='fatal',
            msg='No contact to master for more than 5 minutes')]

    @pytest.mark.xfail(reason="sometimes fail due to race condition in db table creation")
    @pytest.mark.with_replica_thread
    @pytest.mark.with_notifier
    def test_no_master_update(self, plugin, xom, monkeypatch):
        import time
        now = time.time()
        request = self._xomrequest(xom)
        serial = xom.keyfs.get_current_serial()
        xom.keyfs.notifier.wait_event_serial(serial)
        serial = xom.keyfs.get_current_serial()
        xom.keyfs.notifier.wait_event_serial(serial)
        assert hasattr(xom, 'replica_thread')
        assert xom.is_replica()
        # fake last update
        xom.replica_thread.update_from_master_at = now
        # no report in the first minute
        result = plugin(request)
        assert result == []
        # warning after one minute
        monkeypatch.setattr(devpi_server.views, "time", lambda: now + 70)
        result = plugin(request)
        assert result == [dict(
            status='warn',
            msg='No update from master for more than 1 minute')]
        # fatal after five minutes
        monkeypatch.setattr(devpi_server.views, "time", lambda: now + 310)
        result = plugin(request)
        assert result == [dict(
            status='fatal',
            msg='No update from master for more than 5 minutes')]


def test_apiconfig_with_outside_url(testapp):
    testapp.xom.config.args.outside_url = u = "http://outside.com"
    r = testapp.get_json("/root/pypi/+api")
    assert r.status_code == 200
    result = r.json["result"]
    assert "pypisubmit" not in result
    assert result["index"] == u + "/root/pypi"
    assert result["login"] == u + "/+login"
    assert result["simpleindex"] == u + "/root/pypi/+simple/"

    #for name in "pushrelease simpleindex login pypisubmit resultlog".split():
    #    assert name in r.json
    #
    #
def test_root_pypi(testapp):
    r = testapp.get("/root/pypi")
    assert r.status_code == 200

def test_set_versiondata_and_get_description(mapp, testapp):
    api = mapp.create_and_use("user/name")
    metadata = {"name": "pkg1", "version": "1.0", ":action": "submit",
                "description": "hello world"}
    r = testapp.get("/user/name/+simple/pkg1")
    serial = int(r.headers["X-DEVPI-SERIAL"])
    r = testapp.post(api.pypisubmit, metadata)
    new_serial = int(r.headers["X-DEVPI-SERIAL"])
    assert new_serial == serial + 1
    assert r.status_code == 200
    r = testapp.get_json("/user/name/pkg1/1.0")
    assert r.status_code == 200
    assert "hello world" in r.json["result"]["description"]
    r = testapp.get_json("/user/name/pkg1")
    assert r.status_code == 200
    assert "1.0" in r.json["result"]

class TestSubmitValidation:
    @pytest.fixture
    def submit(self, mapp, testapp):
        class Submit:
            def __init__(self, stagename="user/dev"):
                self.stagename = stagename
                self.username = stagename.split("/")[0]
                self.api = mapp.create_and_use(
                    stagename, indexconfig=dict(bases=["root/pypi"]))

            def metadata(self, metadata, code):
                return testapp.post(self.api.pypisubmit, metadata, code=code)

            def file(self, filename, content, metadata, code=200):
                if "version" not in metadata:
                    metadata["version"] = splitbasename(filename,
                                                        checkarch=False)[1]
                return mapp.upload_file_pypi(
                        filename, content,
                        metadata.get("name"), metadata.get("version"),
                        indexname=self.stagename, register=False,
                        code=code)
        return Submit()

    def test_404(self, testapp, mapp):
        testapp.post("/nouser/nostage", {"hello": ""}, code=404)
        mapp.upload_file_pypi("qlwkej", b"qwe", "name", "1.0",
                              indexname="nouser/nostage", code=404)

    def test_metadata_normalize_to_previous_issue84(self, submit, testapp):
        metadata = {"name": "pKg1", "version": "1.0", ":action": "submit",
                    "description": "hello world"}
        submit.metadata(metadata, code=200)
        metadata = {"name": "Pkg1", "version": "2.0", ":action": "submit",
                    "description": "hello world"}
        submit.metadata(metadata, code=200)

    def test_metadata_multifield(self, submit, mapp):
        classifiers = ["Intended Audience :: Developers",
                       "License :: OSI Approved :: MIT License"]
        metadata = {"name": "Pkg1", "version": "1.0", ":action": "submit",
                    "classifiers": classifiers, "platform": ["unix", "win32"]}
        submit.metadata(metadata, code=200)
        data = mapp.getjson("/%s/Pkg1/1.0" % submit.stagename)["result"]
        assert data["classifiers"] == classifiers
        assert data["platform"] == ["unix", "win32"]

    def test_metadata_multifield_singleval(self, submit, mapp):
        classifiers = ["Intended Audience :: Developers"]
        metadata = {"name": "Pkg1", "version": "1.0", ":action": "submit",
                    "classifiers": classifiers}
        submit.metadata(metadata, code=200)
        data = mapp.getjson("/%s/Pkg1/1.0" % submit.stagename)["result"]
        assert data["classifiers"] == classifiers

    def test_metadata_UNKNOWN_handling(self, submit, mapp):
        metadata = {"name": "Pkg1", "version": "1.0", ":action": "submit",
                    "download_url": "UNKNOWN", "platform": ""}
        submit.metadata(metadata, code=200)
        data = mapp.getjson("/%s/Pkg1/1.0" % submit.stagename)["result"]
        assert not data["download_url"]
        assert not data["platform"]

    def test_upload_file(self, submit, mapp):
        metadata = {"name": "Pkg5", "version": "1.0", ":action": "submit"}
        submit.metadata(metadata, code=200)
        r = submit.file("pkg5-2.6.tgz", b"123", {"name": "pkg5some"}, code=400)
        assert "no project" in r.status
        submit.file("pkg5-2.6.tgz", b"123", {"name": "Pkg5"}, code=200)
        r = submit.file("pkg5-2.6.qwe", b"123", {"name": "Pkg5"}, code=400)
        assert "not a valid" in r.status
        r = submit.file("pkg5-2.7.tgz", b"123", {"name": "pkg5"}, code=200)
        mapp.get_release_paths("Pkg5")

    def test_upload_file_version_not_in_filename(self, submit, mapp):
        metadata = {"name": "Pkg5", "version": "1.0", ":action": "submit"}
        submit.metadata(metadata, code=200)
        r = submit.file("pkg5-0.0.0.tgz", b"123", {"name": "Pkg5", "version": "1.0"},
                        code=400)
        assert "does not contain version" in r.status

    def test_upload_use_registered_name_issue84(self, submit, mapp):
        metadata = {"name": "pkg_hello", "version":"1.0", ":action": "submit"}
        submit.metadata(metadata, code=200)
        submit.file("pkg-hello-1.0.whl", b"123", {"name": "pkg-hello",
                                              "version": "1.0"}, code=200)
        paths = mapp.get_release_paths("pkg_hello")
        assert paths[0].endswith("pkg-hello-1.0.whl")

    def test_upload_and_delete_name_normalization_issue98(self, mapp,
            submit, testapp):
        metadata = {"name": "pkg_hello", "version":"1.0", ":action": "submit"}
        submit.metadata(metadata, code=200)
        submit.file("pkg-hello-1.0.whl", b"123", {"name": "pkg-hello",
                                              "version": "1.0"}, code=200)
        metadata = {"name": "pkg_hello", "version":"1.1", ":action": "submit"}
        submit.metadata(metadata, code=200)
        submit.file("pkg-hello-1.1.whl", b"123", {"name": "pkg-hello",
                                              "version": "1.1"}, code=200)
        r = testapp.delete(submit.api.index + "/pkg-hello/1.1")
        assert r.status_code == 200
        assert len(mapp.get_release_paths("pkg_hello")) == 1
        r = testapp.delete(submit.api.index + "/pkg-hello")
        assert r.status_code == 200

    def test_upload_and_simple_index_with_redirect(self, submit, testapp):
        metadata = {"name": "Pkg5", "version": "2.6", ":action": "submit"}
        submit.metadata(metadata, code=200)
        submit.file("pkg5-2.6.tgz", b"123", {"name": "Pkg5"}, code=200)
        r = testapp.get("/%s/+simple/Pkg5" % submit.stagename, follow=False)
        assert r.status_code == 302
        assert r.location.endswith("pkg5")
        r = testapp.get(r.location)
        assert r.status_code == 200

    def test_upload_and_delete_index(self, submit, testapp, mapp):
        metadata = {"name": "Pkg5", "version": "2.6", ":action": "submit"}
        submit.metadata(metadata, code=200)
        submit.file("pkg5-2.6.tgz", b"123", {"name": "Pkg5"}, code=200)
        submit.file("pkg5-2.7.tgz", b"123", {"name": "Pkg5"}, code=200)
        paths = mapp.get_release_paths("Pkg5")
        for path in paths:
            testapp.xget(200, path)
            with testapp.xom.keyfs.transaction():
                entry = testapp.xom.filestore.get_file_entry(path.strip("/"))
                assert entry.file_exists()
        # try a slightly different path and see if it fails
        testapp.xget(404, path[:-2])

        mapp.delete_index(submit.stagename)
        for path in paths:
            testapp.xget(410, path)
            with testapp.xom.keyfs.transaction():
                entry = testapp.xom.filestore.get_file_entry(path.strip("/"))
                assert not entry.file_exists()

    def test_delete_verdata_noacl_issue179(self, submit, testapp, mapp):
        metadata = {"name": "pkg5", "version": "2.6", ":action": "submit"}
        submit.metadata(metadata, code=200)
        mapp.create_and_login_user("user2")
        testapp.xdel(403, "/%s/pkg5/2.6" % submit.stagename)

    def test_upload_and_delete_user_issue130(self, submit, testapp, mapp):
        metadata = {"name": "pkg5", "version": "2.6", ":action": "submit"}
        submit.metadata(metadata, code=200)
        submit.file("pkg5-2.6.tgz", b"123", {"name": "pkg5"}, code=200)
        assert mapp.get_release_paths("pkg5")
        mapp.delete_user(submit.username)
        # recreate user and index
        submit = submit.__class__(submit.stagename)
        mapp.get_simple("pkg5", code=404)

    def test_upload_twice_to_nonvolatile(self, submit, testapp, mapp):
        mapp.modify_index(submit.stagename, indexconfig=dict(volatile=False))
        metadata = {"name": "Pkg5", "version": "2.6", ":action": "submit"}
        submit.metadata(metadata, code=200)
        submit.file("pkg5-2.6.tgz", b"123", {"name": "Pkg5"}, code=200)
        mapp.upload_doc("pkg5-2.6.doc.zip", b"123", "pkg5", "2.6", code=200)
        path1, = mapp.get_release_paths("Pkg5")
        testapp.xget(200, path1)
        # we now try to upload a different file which should fail
        r = submit.file("pkg5-2.6.tgz", b"1234", {"name": "Pkg5"}, code=409)
        assert '409 pkg5-2.6.tgz already exists in non-volatile index' in r.text
        # import pdb; pdb.set_trace()
        r = mapp.upload_doc("pkg5-2.6.doc.zip", b"1234", "Pkg5", "2.6", code=409)
        assert '409 pkg5-2.6.doc.zip already exists in non-volatile index' in r.text
        # if we upload the same file as originally, then it's a no op
        r = submit.file("pkg5-2.6.tgz", b"123", {"name": "Pkg5"}, code=200)
        assert '200 Upload of identical file to non volatile index.' in r.text
        r = mapp.upload_doc("pkg5-2.6.doc.zip", b"123", "Pkg5", "2.6", code=200)
        assert '200 Upload of identical file to non volatile index.' in r.text
        path2, = mapp.get_release_paths("Pkg5")
        # check that nothing changed
        assert path1 == path2
        r = testapp.xget(200, path2)
        assert r.body == b'123'
        r = testapp.xget(200, "%s/Pkg5/2.6" % mapp.api.index,
                         accept="application/json")
        links = r.json['result']['+links']
        assert len(links) == 2
        for link in links:
            log1, = link['log']
            assert sorted(log1.keys()) == ['dst', 'what', 'when', 'who']
            assert log1['what'] == 'upload'
            assert log1['who'] == 'user'
            assert log1['dst'] == 'user/dev'

    def test_upload_twice_to_volatile(self, submit, testapp, mapp):
        metadata = {"name": "Pkg5", "version": "2.6", ":action": "submit"}
        submit.metadata(metadata, code=200)
        submit.file("pkg5-2.6.tgz", b"123", {"name": "Pkg5"}, code=200)
        mapp.upload_doc("pkg5-2.6.doc.zip", b'', "pkg5", "2.6", code=200)
        path1, = mapp.get_release_paths("Pkg5")
        testapp.xget(200, path1)
        submit.file("pkg5-2.6.tgz", b"1234", {"name": "Pkg5"}, code=200)
        mapp.upload_doc("pkg5-2.6.doc.zip", b"1234", "Pkg5", "2.6", code=200)
        path2, = mapp.get_release_paths("Pkg5")
        testapp.xget(410, path1)  # existed once but deleted during overwrite
        testapp.xget(200, path2)
        r = testapp.xget(200, "%s/Pkg5/2.6" % mapp.api.index,
                         accept="application/json")
        links = r.json['result']['+links']
        assert len(links) == 2
        for link in links:
            log1, log2 = link['log']
            assert sorted(log1.keys()) == ['count', 'what', 'when', 'who']
            assert log1['what'] == 'overwrite'
            assert log1['who'] is None
            assert log1['count'] == 1
            assert sorted(log2.keys()) == ['dst', 'what', 'when', 'who']
            assert log2['what'] == 'upload'
            assert log2['who'] == 'user'
            assert log2['dst'] == 'user/dev'

    def test_upload_thrice_and_push(self, submit, testapp, mapp):
        metadata = {"name": "Pkg5", "version": "2.6", ":action": "submit"}
        submit.metadata(metadata, code=200)
        submit.file("pkg5-2.6.tgz", b"123", {"name": "Pkg5"}, code=200)
        submit.file("pkg5-2.6.tgz", b"1234", {"name": "Pkg5"}, code=200)
        submit.file("pkg5-2.6.tgz", b"12345", {"name": "Pkg5"}, code=200)
        r = testapp.xget(200, "%s/Pkg5/2.6" % mapp.api.index,
                         accept="application/json")
        link, = r.json['result']['+links']
        log1, log2 = link['log']
        assert sorted(log1.keys()) == ['count', 'what', 'when', 'who']
        assert log1['what'] == 'overwrite'
        assert log1['who'] is None
        assert log1['count'] == 2
        assert sorted(log2.keys()) == ['dst', 'what', 'when', 'who']
        assert log2['what'] == 'upload'
        assert log2['who'] == 'user'
        assert log2['dst'] == 'user/dev'
        old_stage = mapp.api.stagename
        mapp.create_index('prod')
        new_stage = mapp.api.stagename
        mapp.use(old_stage)
        req = dict(name="Pkg5", version="2.6", targetindex=new_stage)
        r = testapp.push("/%s" % old_stage, json.dumps(req))
        r = testapp.xget(200, "/%s/Pkg5/2.6" % new_stage,
                         accept="application/json")
        link, = r.json['result']['+links']
        # the overwrite info should be gone
        log1, log2 = link['log']
        assert sorted(log1.keys()) == ['dst', 'what', 'when', 'who']
        assert log1['what'] == 'upload'
        assert log1['who'] == 'user'
        assert log1['dst'] == 'user/dev'
        assert sorted(log2.keys()) == ['dst', 'src', 'what', 'when', 'who']
        assert log2['what'] == 'push'
        assert log2['who'] == 'user'
        assert log2['dst'] == 'user/prod'
        assert log2['src'] == 'user/dev'

    def test_last_modified_preserved_on_push(self, submit, testapp, mapp):
        import time
        metadata = {"name": "Pkg5", "version": "2.6", ":action": "submit"}
        submit.metadata(metadata, code=200)
        submit.file("pkg5-2.6.tgz", b"1234", {"name": "Pkg5"}, code=200)
        old_stagename = mapp.api.stagename
        mapp.create_index('prod')
        new_stagename = mapp.api.stagename
        mapp.use(old_stagename)
        req = dict(name="Pkg5", version="2.6", targetindex=new_stagename)
        time.sleep(1.5)  # needed to test last_modified below
        testapp.push("/%s" % old_stagename, json.dumps(req))
        with mapp.xom.model.keyfs.transaction(write=False):
            old_stage = mapp.xom.model.getstage(old_stagename)
            new_stage = mapp.xom.model.getstage(new_stagename)
            old_entry = old_stage.get_releaselinks('Pkg5')[0].entry
            new_entry = new_stage.get_releaselinks('Pkg5')[0].entry
            assert old_entry.last_modified == new_entry.last_modified

    def test_pypiaction_not_in_verdata_after_push(self, submit, testapp, mapp):
        metadata = {"name": "Pkg5", "version": "2.6", ":action": "submit"}
        submit.metadata(metadata, code=200)
        submit.file("pkg5-2.6.tgz", b"1234", {"name": "Pkg5"}, code=200)
        old_stagename = mapp.api.stagename
        mapp.create_index('prod')
        new_stagename = mapp.api.stagename
        mapp.use(old_stagename)
        req = dict(name="Pkg5", version="2.6", targetindex=new_stagename)
        testapp.push("/%s" % old_stagename, json.dumps(req))
        with mapp.xom.model.keyfs.transaction(write=False):
            new_stage = mapp.xom.model.getstage(new_stagename)
            verdata = new_stage.get_versiondata('Pkg5', '2.6')
            assert ':action' not in list(verdata.keys())

    def test_upload_with_metadata(self, submit, testapp, mapp, pypistage):
        pypistage.mock_simple("package", '<a href="/package-1.0.zip" />')
        mapp.upload_file_pypi(
                        "package-1.0.tar.gz", b'123',
                        "package", "1.0",
                        indexname=submit.stagename, register=False,
                        code=200)

    def test_get_project_redirected(self, submit, mapp):
        metadata = {"name": "Pkg1", "version": "1.0", ":action": "submit",
                    "description": "hello world"}
        submit.metadata(metadata, code=200)
        mapp.getjson("/%s/pkg1" % submit.stagename, code=200)
        #assert location.endswith("/Pkg1")


def test_submit_authorization(mapp, testapp):
    from base64 import b64encode
    import sys
    api = mapp.create_and_use()
    testapp.auth = None
    data = {':action': 'submit', "name": "Pkg1", "version": "1.0"}
    r = testapp.post(api.index + '/', data, expect_errors=True)
    assert r.status_code == 401
    assert 'WWW-Authenticate' in r.headers
    basic_auth = '%s:%s' % (api.user, api.password)
    basic_auth = b"Basic " + b64encode(basic_auth.encode("ascii"))
    if sys.version_info[0] >= 3:
        basic_auth = basic_auth.decode("ascii")
    headers = {'Authorization': basic_auth}
    r = testapp.post(api.index + '/', data, headers=headers)
    assert r.status_code == 200


def test_push_non_existent(mapp, testapp, monkeypatch):
    req = dict(name="pkg5", version="2.6", targetindex="user2/dev")
    # check redirection/404 (depending on if devpi-web is installed,
    # status_code is different)
    r = testapp.push("/user2/dev/", json.dumps(req), expect_errors=True)
    assert r.status_code in (302, 404)

    # check that push to from non-existent index results in 404
    r = testapp.push("/user2/dev", json.dumps(req), expect_errors=True)
    assert r.status_code == 404
    mapp.create_and_login_user("user1", "1")
    mapp.create_index("dev")

    # check that push to non-existent target index results in error
    r = testapp.push("/user1/dev", json.dumps(req), expect_errors=True)
    assert r.status_code == 400

    mapp.create_and_login_user("user2")
    mapp.create_index("dev", indexconfig=dict(acl_upload=["user2"]))
    mapp.login("user1", "1")
    # check push of non-existent release results in error
    r = testapp.push("/user1/dev", json.dumps(req), expect_errors=True)
    assert r.status_code == 400
    #
    mapp.use("user1/dev")
    mapp.upload_file_pypi("pkg5-2.6.tgz", b"123", "pkg5", "2.6")
    # check that push to non-authorized existent target index results in error
    r = testapp.push("/user1/dev", json.dumps(req), expect_errors=True)
    assert r.status_code == 401

def test_push_from_base_error(mapp, testapp, monkeypatch, pypistage):
    pypistage.mock_simple("hello", text='<a href="hello-1.0.tar.gz"/>')
    mapp.create_and_login_user("user1", "1")
    mapp.create_index("prod", indexconfig=dict(bases=["root/pypi"]))
    mapp.create_index("dev", indexconfig=dict(bases=["user1/prod"]))
    req = dict(name="hello", version="1.0", targetindex="user1/prod")
    r = testapp.push("/user1/dev", json.dumps(req), expect_errors=True)
    assert r.status_code == 400
    assert "no files for" in r.json["message"]


def test_push_from_pypi(httpget, mapp, pypistage, testapp):
    pypistage.mock_simple("hello", text='<a href="hello-1.0.tar.gz"/>')
    pypistage.mock_extfile("/simple/hello/hello-1.0.tar.gz", b"123")
    mapp.create_and_login_user("foo")
    mapp.create_index("newindex1", indexconfig=dict(bases=["root/pypi"]))
    mapp.use("root/pypi")
    req = dict(name="hello", version="1.0", targetindex="foo/newindex1")
    r = testapp.push("/root/pypi", json.dumps(req))
    assert r.status_code == 200
    assert r.json == {
        'result': [
            [200, 'register', 'hello', '1.0', '->', 'foo/newindex1'],
            [200, 'store_releasefile',
             'foo/newindex1/+f/a66/5a45920422f9d/hello-1.0.tar.gz']],
        'type': 'actionlog'}


def test_push_from_pypi_fail(httpget, mapp, pypistage, testapp):
    pypistage.mock_simple("hello", text='<a href="hello-1.0.tar.gz"/>')
    pypistage.mock_extfile("/simple/hello/hello-1.0.tar.gz", b"123", status_code=502)
    mapp.create_and_login_user("foo")
    mapp.create_index("newindex1", indexconfig=dict(bases=["root/pypi"]))
    mapp.use("root/pypi")
    req = dict(name="hello", version="1.0", targetindex="foo/newindex1")
    r = testapp.push("/root/pypi", json.dumps(req))
    assert r.status_code == 502
    assert r.json["message"] == "error 502 getting https://pypi.python.org/simple/hello/hello-1.0.tar.gz"


def test_upload_docs_without_registration(mapp, testapp, monkeypatch):
    mapp.create_and_use()
    mapp.upload_file_pypi("pkg1-2.6.tgz", b"123", "pkg1", "2.6")
    mapp.upload_doc("pkg1-2.7.doc.zip", b'', "pkg1", "2.7", code=400)

@proj
def test_upload_and_push_internal(mapp, testapp, monkeypatch, proj):
    mapp.create_user("user1", "1")
    mapp.create_and_login_user("user2")
    mapp.create_index("prod", indexconfig=dict(acl_upload=["user1", "user2"]))
    mapp.create_index("dev", indexconfig=dict(acl_upload=["user2"]))

    mapp.login("user1", "1")
    mapp.create_index("dev")
    mapp.use("user1/dev")
    mapp.upload_file_pypi("pkg1-2.6.tgz", b"123", "pkg1", "2.6")
    content = zip_dict({"index.html": "<html/>"})
    mapp.upload_doc("pkg1.zip", content, "pkg1", "")

    # check that push is authorized and executed towards user2/prod index
    req = dict(name="pkg1", version="2.6", targetindex="user2/prod")
    r = testapp.push("/user1/dev", json.dumps(req))
    assert r.status_code == 200
    vv = get_view_version_links(testapp, "/user2/prod", "pkg1", "2.6",
                                proj=proj)
    link = vv.get_link(rel="releasefile")
    history_log = link.log
    assert len(history_log) == 2
    assert history_log[0]['what'] == 'upload'
    assert history_log[0]['who'] == 'user1'
    assert history_log[0]['dst'] == 'user1/dev'
    assert history_log[1]['what'] == 'push'
    assert history_log[1]['who'] == 'user1'
    assert history_log[1]['src'] == 'user1/dev'
    assert history_log[1]['dst'] == 'user2/prod'
    assert link.href.endswith("/pkg1-2.6.tgz")
    # we check here that the upload of docs without version was
    # automatically tied to the newest release metadata
    link = vv.get_link(rel="doczip")
    history_log = link.log
    assert len(history_log) == 2
    assert history_log[0]['what'] == 'upload'
    assert history_log[0]['who'] == 'user1'
    assert history_log[0]['dst'] == 'user1/dev'
    assert history_log[1]['what'] == 'push'
    assert history_log[1]['who'] == 'user1'
    assert history_log[1]['src'] == 'user1/dev'
    assert history_log[1]['dst'] == 'user2/prod'
    assert link.href.endswith("/pkg1-2.6.doc.zip")
    r = testapp.get(link.href)
    archive = Archive(py.io.BytesIO(r.body))
    assert 'index.html' in archive.namelist()

    # reconfigure inheritance and see if get shadowing information
    mapp.modify_index("user1/dev", indexconfig=dict(bases=("/user2/prod",)))
    vv = get_view_version_links(testapp, "/user1/dev", "pkg1", "2.6", proj=proj)
    link = vv.get_link(rel="releasefile")
    assert link.href.endswith("/pkg1-2.6.tgz")
    shadows = vv.shadowed()
    assert len(shadows) == 1, vv.versiondata
    vv = shadows[0]
    link = vv.get_link(rel="releasefile")
    assert link.href.endswith("/pkg1-2.6.tgz")


@pytest.mark.parametrize("outside_url", ['', 'http://localhost/devpi'])
def test_upload_and_push_with_toxresults(mapp, testapp, outside_url):
    from test_devpi_server.example import tox_result_data
    mapp.create_and_login_user("user1", "1")
    mapp.create_index("prod")
    mapp.create_index("dev")
    mapp.use("user1/dev")
    mapp.upload_file_pypi("pkg1-2.6.tgz", b"123", "pkg1", "2.6", code=200)
    path, = mapp.get_release_paths("pkg1")
    headers={str('X-outside-url'): str(outside_url)}
    r = testapp.post(path, json.dumps(tox_result_data), headers=headers)
    # store a second toxresult
    r = testapp.post(path, json.dumps(tox_result_data), headers=headers)
    assert r.status_code == 200
    testapp.xget(200, path, headers=headers)
    req = dict(name="pkg1", version="2.6", targetindex="user1/prod")
    r = testapp.push("/user1/dev", json.dumps(req), headers=headers)
    for actionlog in r.json["result"]:
        assert "user1/dev" not in actionlog[-1]

    vv = get_view_version_links(testapp, "/user1/prod", "pkg1", "2.6")
    history_log = vv.get_link('releasefile').log
    assert len(history_log) == 2
    assert history_log[0]['what'] == 'upload'
    assert history_log[0]['dst'] == 'user1/dev'
    assert history_log[1]['what'] == 'push'
    assert history_log[1]['who'] == 'user1'
    assert history_log[1]['src'] == 'user1/dev'
    assert history_log[1]['dst'] == 'user1/prod'

    links = vv.get_links("toxresult")
    assert len(links) == 2
    link1, link2 = links
    assert "user1/prod" in link1.href
    pkgmeta = json.loads(testapp.get(link1.href).body.decode("utf8"))

    assert pkgmeta == tox_result_data
    history_log = link1.log
    assert len(history_log) == 2
    assert history_log[0]['what'] == 'upload'
    assert history_log[0]['dst'] == 'user1/dev'
    assert history_log[1]['what'] == 'push'
    assert history_log[1]['who'] == 'user1'
    assert history_log[1]['src'] == 'user1/dev'
    assert history_log[1]['dst'] == 'user1/prod'


def test_upload_and_push_external(mapp, testapp, reqmock):
    api = mapp.create_and_use()
    mapp.upload_file_pypi("pkg1-2.6.tgz", b"123", "pkg1", "2.6")
    zipcontent = zip_dict({"index.html": "<html/>"})
    mapp.upload_doc("pkg1.zip", zipcontent, "pkg1", "")

    r = testapp.get(api.simpleindex + "pkg1")
    assert r.status_code == 200
    a = getfirstlink(r.text)
    assert "pkg1-2.6.tgz" in a.get("href")

    # get root index page
    r = testapp.get(api.index)
    assert r.status_code == 200

    # push OK
    req = dict(name="pkg1", version="2.6", posturl="http://whatever.com/",
               username="user", password="password")
    rec = reqmock.mockresponse(url=None, code=200, method="POST", data="msg")
    body = json.dumps(req).encode("utf-8")
    r = testapp.request(api.index, method="PUSH", body=body,
                        expect_errors=True)
    assert r.status_code == 200
    assert len(rec.requests) == 3
    for i in range(3):
        assert rec.requests[i].url == req["posturl"]
    req = rec.requests[2]
    # XXX properly decode www-url-encoded body and check zipcontent
    assert b"pkg1.zip" in req.body
    assert zipcontent in req.body

    # push with error
    reqmock.mockresponse(url=None, code=500, method="POST")
    r = testapp.request(api.index, method="PUSH", body=body, expect_errors=True)
    assert r.status_code == 502
    result = r.json["result"]
    assert len(result) == 1
    assert result[0][0] == 500

def test_upload_and_push_egg(mapp, testapp, reqmock):
    api = mapp.create_and_use()
    mapp.upload_file_pypi("pkg2-1.0-py27.egg", b"123", "pkg2", "1.0")
    r = testapp.get(api.simpleindex + "pkg2")
    assert r.status_code == 200
    a = getfirstlink(r.text)
    assert "pkg2-1.0-py27.egg" in a.get("href")

    # push
    req = dict(name="pkg2", version="1.0", posturl="http://whatever.com/",
               username="user", password="password")
    rec = reqmock.mockresponse(url=None, data=b"msg", code=200)
    r = testapp.push(api.index, json.dumps(req))
    assert r.status_code == 200
    assert len(rec.requests) == 2
    assert rec.requests[0].url == req["posturl"]
    assert rec.requests[1].url == req["posturl"]

def test_upload_and_delete_project(mapp, testapp):
    api = mapp.create_and_use()
    mapp.delete_project("pkg1", code=404)
    mapp.upload_file_pypi("pkg1-2.6.tgz", b"123", "pkg1", "2.6")
    mapp.upload_file_pypi("pkg1-2.7.tgz", b"123", "pkg1", "2.7")
    r = testapp.get(api.simpleindex + "pkg1")
    assert r.status_code == 200
    r = testapp.delete(api.index + "/pkg1/2.6")
    assert r.status_code == 200
    mapp.getjson(api.index + "/pkg1", code=200)
    r = testapp.delete(api.index + "/pkg1/2.7")
    assert r.status_code == 200
    mapp.getjson(api.index + "/pkg1", code=404)
    mapp.getjson(api.index + "/pkg1/2.7", code=404)

def test_upload_with_acl(mapp):
    mapp.login("root")
    mapp.change_password("root", "123")
    mapp.create_user("user", "123")
    api = mapp.create_and_use()  # new context and login
    mapp.login("user", "123")
    # user cannot write to index now
    mapp.upload_file_pypi("pkg1-2.6.tgz", b"123", "pkg1", "2.6", code=403)
    mapp.login(api.user, api.password)
    mapp.set_acl(["user"])
    mapp.login("user", "123")
    # we need to skip setting the whitelist here, because the user may only
    # register and upload a package, but not modify the index
    mapp.upload_file_pypi("pkg1-2.6.tgz", b"123", "pkg1", "2.6",
                          set_whitelist=False)


def test_upload_anonymously(mapp):
    mapp.login("root")
    mapp.create_and_use()  # new context and login
    mapp.set_versiondata(dict(name="pkg1", version="1.0"))
    mapp.logout()
    # anonymous cannot write to index now
    mapp.upload_file_pypi("pkg1-2.6.tgz", b"123", "pkg1", "2.6", code=401)
    # now we change the acl
    mapp.login("root")
    mapp.set_acl([":anonymous:"])
    mapp.logout()
    # we need to skip setting the whitelist here, because the user may only
    # register and upload a package, but not modify the index
    mapp.upload_file_pypi("pkg1-2.6.tgz", b"123", "pkg1", "2.6",
                          set_whitelist=False)


class TestPluginPermissions:
    @pytest.fixture
    def plugin(self):
        class Plugin:
            groups = ['plugingroup']
            def devpiserver_auth_user(self, userdict, username, password):
                if username == 'pluginuser':
                    return dict(status="ok", groups=self.groups)
                return dict(status="unknown")
        return Plugin()

    @pytest.fixture
    def xom(self, makexom, plugin):
        xom = makexom(plugins=[plugin])
        return xom

    def test_plugin_upload_group(self, mapp, plugin):
        mapp.login("root")
        mapp.create_and_use()  # new context and login
        mapp.set_versiondata(dict(name="pkg1", version="1.0"))
        mapp.login("pluginuser")
        # pluginuser cannot write to index now
        mapp.upload_file_pypi("pkg1-2.6.tgz", b"123", "pkg1", "2.6", code=403)
        # now we change the acl
        mapp.login("root")
        mapp.set_acl([":plugingroup"])
        mapp.login("pluginuser")
        # we need to skip setting the whitelist here, because the user may only
        # register and upload a package, but not modify the index
        mapp.upload_file_pypi("pkg1-2.6.tgz", b"123", "pkg1", "2.6",
                              set_whitelist=False)
        # if we remove the user from the group (and login again, as the groups
        # are stored in the token) she can't upload anymore
        plugin.groups = []
        mapp.login("pluginuser")
        mapp.upload_file_pypi("pkg1-2.6.tgz", b"123", "pkg1", "2.6", code=403)

    def test_plugin_user_create_index(self, mapp):
        mapp.login("pluginuser")
        assert "pluginuser" not in mapp.getuserlist()
        mapp.create_index("pluginuser/dev")
        assert "pluginuser" in mapp.getuserlist()
        assert sorted(mapp.getindexlist("pluginuser")) == ['pluginuser/dev']


def test_upload_trigger(mapp):
    class Plugin:
        def devpiserver_on_upload_sync(self, log, application_url,
                                       stage, project, version):
            self.results.append(
                (application_url, stage.name, project, version))
    plugin = Plugin()
    plugin.results = []
    mapp.xom.config.pluginmanager.register(plugin)
    mapp.create_and_use()
    mapp.upload_file_pypi("pkg1-2.6.tgz", b"123", "pkg1", "2.6", code=200)
    assert plugin.results == [
        ('http://localhost', 'user1/dev', 'pkg1', '2.6')]


def test_upload_and_testdata(mapp, testapp):
    from test_devpi_server.example import tox_result_data
    api = mapp.create_and_use()
    mapp.upload_file_pypi("pkg1-2.6.tgz", b"123", "pkg1", "2.6", code=200)
    path, = mapp.get_release_paths("pkg1")
    testapp.xget(200, path)
    import json
    r = testapp.post(path, json.dumps(tox_result_data))
    assert r.status_code == 200
    vv = get_view_version_links(testapp, api.index, "pkg1", "2.6", proj=proj)
    link = vv.get_link("toxresult")
    pkgmeta = json.loads(testapp.get(link.href).body.decode("utf8"))
    assert pkgmeta == tox_result_data
    assert link.for_href.endswith(path)


@proj
def test_upload_and_access_releasefile_meta(mapp, testapp, proj):
    api = mapp.create_and_use()
    content = b"123"
    mapp.upload_file_pypi("pkg5-2.6.tgz", content, "pkg5", "2.6")
    vv = get_view_version_links(testapp, api.index, "pkg5", "2.6", proj=proj)
    link = vv.get_link("releasefile")
    pkgmeta = mapp.getjson(link.href)
    assert pkgmeta["type"] == "releasefilemeta"
    hash_spec = pkgmeta["result"]["hash_spec"]
    assert hash_spec_matches(hash_spec, content)

def test_upload_and_delete_project_version(mapp):
    api = mapp.create_and_use()
    mapp.delete_project("pkg1", code=404)
    mapp.upload_file_pypi("pkg1-2.6.tgz", b"123", "pkg1", "2.6")
    mapp.upload_file_pypi("pkg1-2.7.tgz", b"123", "pkg1", "2.7")
    mapp.get_simple("pkg1", code=200)
    mapp.delete_project("pkg1/1.0", code=404)
    mapp.delete_project("pkg1/2.6", code=200)
    assert mapp.getjson(api.index + "/pkg1")["result"]
    mapp.delete_project("pkg1/2.7", code=200)
    #assert mapp.getjson("/user/name/pkg1/")["status"] == 404
    mapp.getjson(api.index + "pkg1", code=404)

def test_delete_version_fails_on_non_volatile(mapp):
    mapp.create_and_use(indexconfig=dict(volatile=False))
    mapp.upload_file_pypi("pkg1-2.6.tgz", b"123", "pkg1", "2.6")
    mapp.delete_project("pkg1/2.6", code=403)


def test_upload_to_mirror_fails(mapp):
    mapp.upload_file_pypi(
            "pkg1-2.6.tgz", b"123", "pkg1", "2.6", code=404,
            indexname="root/pypi")

def test_delete_from_mirror_fails(mapp):
    mapp.login_root()
    mapp.use("root/pypi")
    mapp.delete_project("pytest/2.3.5", code=405)
    mapp.delete_project("pytest", code=405)

def test_delete_volatile_fails(mapp):
    mapp.login_root()
    mapp.create_index("test", indexconfig=dict(volatile=False))
    mapp.use("root/test")
    mapp.upload_file_pypi("pkg5-2.6.tgz", b"123", "pkg5", "2.6")
    mapp.delete_project("pkg5", code=403)


@pytest.mark.parametrize("volatile", [True, False])
@pytest.mark.parametrize("restrict_modify", [None, "root"])
def test_delete_with_acl_upload(mapp, restrict_modify, volatile, xom):
    xom.config.args.restrict_modify = restrict_modify
    mapp.login_root()
    mapp.create_user("user1", "1")
    mapp.create_index("user1/dev", indexconfig=dict(
        acl_upload=["user2"],
        volatile=volatile))
    mapp.create_and_login_user("user2")
    mapp.use("user1/dev")
    mapp.upload_file_pypi(
        "pkg5-2.6.tgz", b"123", "pkg5", "2.6", set_whitelist=False)
    mapp.upload_file_pypi(
        "pkg5-2.7.tgz", b"123", "pkg5", "2.7", set_whitelist=False)
    result_code = 200 if volatile else 403
    mapp.delete_project('pkg5/2.6', code=result_code)
    mapp.delete_project('pkg5', code=result_code)


@proj
def test_upload_docs_no_version(mapp, testapp, proj):
    api = mapp.create_and_use()
    content = zip_dict({"index.html": "<html/>"})
    mapp.set_versiondata(dict(name="Pkg1", version="1.0"))
    mapp.upload_doc("pkg1.zip", content, "Pkg1", "")
    vv = get_view_version_links(testapp, api.index, "Pkg1", "1.0", proj=proj)
    link = vv.get_link("doczip")
    assert link.href.endswith("/pkg1-1.0.doc.zip")
    r = testapp.get(link.href)
    archive = Archive(py.io.BytesIO(r.body))
    assert 'index.html' in archive.namelist()

def test_upload_docs_no_project_ever_registered(mapp, testapp):
    mapp.create_and_use()
    content = zip_dict({"index.html": "<html/>"})
    mapp.upload_doc("pkg1.zip", content, "pkg1", "", code=400)

@proj
def test_upload_docs(mapp, testapp, proj):
    api = mapp.create_and_use()
    content = zip_dict({"index.html": "<html/>"})
    mapp.upload_doc("pkg1.zip", content, "pkg1", "2.6", code=400)
    mapp.set_versiondata({"name": "pkg1", "version": "2.6"})
    mapp.upload_doc("pkg1.zip", content, "pkg1", "2.6", code=200)
    vv = get_view_version_links(testapp, api.index, "pkg1", "2.6", proj=proj)
    link = vv.get_link(rel="doczip")
    assert link.href.endswith("/pkg1-2.6.doc.zip")
    assert len(link.log) == 1
    assert link.log[0]['what'] == 'upload'
    assert link.log[0]['who'] == 'user1'
    assert link.log[0]['dst'] == 'user1/dev'
    r = testapp.get(link.href)
    archive = Archive(py.io.BytesIO(r.body))
    assert 'index.html' in archive.namelist()


def get_view_version_links(testapp, index, name, version, proj=False):
    if proj:
        url = "/".join([index, name])
        r = testapp.get_json(url, expect_errors=False)
        return ViewLinkStore(url, r.json["result"][version])
    else:
        url = "/".join([index, name, version])
        r = testapp.get_json(url, expect_errors=False)
        return ViewLinkStore(url, r.json["result"])


def test_wrong_login_format(testapp, mapp):
    api = mapp.getapi()
    r = testapp.post(api.login, "qweqweqwe", expect_errors=True)
    assert r.status_code == 400
    r = testapp.post_json(api.login, {"qwelk": ""}, expect_errors=True)
    assert r.status_code == 400


@pytest.mark.parametrize("headers, environ, outsideurl, expected", [
    (
        {"X-outside-url": "http://outside.com"}, {},
        None, "http://outside.com"),
    (
        {"X-outside-url": "http://outside.com/foo"}, {},
        None, "http://outside.com/foo"),
    (
        {"Host": "outside3.com"}, {},
        None, "http://outside3.com"),
    (
        {"Host": "outside3.com"}, {'wsgi.url_scheme': 'https'},
        None, "https://outside3.com"),
    (
        {"Host": "outside3.com:3141"}, {},
        None, "http://outside3.com:3141"),
    (
        {"Host": "outside3.com:3141"}, {'wsgi.url_scheme': 'https'},
        None, "https://outside3.com:3141"),
    # outside url takes precedence over headers
    (
        {"X-outside-url": "http://outside.com"}, {},
        "http://outside2.com", "http://outside2.com"),
    (
        {"X-outside-url": "http://outside.com"}, {},
        "http://outside2.com/foo", "http://outside2.com/foo"),
    (
        {"Host": "outside3.com"}, {},
        "http://out.com", "http://out.com"),
    (
        {"Host": "outside3.com"}, {'wsgi.url_scheme': 'https'},
        "http://out.com", "http://out.com")])
def test_outside_url_middleware(headers, environ, outsideurl, expected, testapp):
    headers = dict((str(k), str(v)) for k, v in headers.items())
    environ = dict((str(k), str(v)) for k, v in environ.items())
    testapp.xom.config.args.outside_url = outsideurl
    r = testapp.get('/+api', headers=headers, extra_environ=environ)
    assert r.json['result']['login'] == "%s/+login" % expected


@pytest.mark.parametrize("stagename", [None, "root/pypi"])
class TestOfflineMode:
    @pytest.fixture
    def xom(self, makexom):
        return makexom(["--offline-mode"])

    def _prepare(self, mapp, pypistage, stagename):
        pypistage.mock_simple("package", '<a href="/package-1.0.zip" />', serial=100)
        if stagename is None:
            api = mapp.create_and_use(indexconfig=dict(bases=["root/pypi"]))
        else:
            api = mapp.use(stagename)
        return api.stagename

    def test_file_not_available(self, mapp, model, testapp, pypistage, stagename):
        stagename = self._prepare(mapp, pypistage, stagename)
        testapp.xget(200, "/%s/+simple/package" % stagename)
        with model.keyfs.transaction(write=False):
            is_fresh, links, serial = pypistage._load_cache_links("package")

        assert len(links) == 0

    def test_file_available(self, mapp, model, testapp, pypistage, monkeypatch, stagename):
        stagename = self._prepare(mapp, pypistage, stagename)
        monkeypatch.setattr(devpi_server.filestore.FileEntry, "file_exists", lambda a: True)
        testapp.xget(200, "/%s/+simple/package" % stagename)
        with model.keyfs.transaction(write=False):
            is_fresh, links, serial = pypistage._load_cache_links("package")

        assert links[0][0] == "package-1.0.zip"


class Test_getjson:
    @pytest.fixture
    def abort_calls(self, monkeypatch):
        l = []
        def recorder(*args, **kwargs):
            l.append((args, kwargs))
            raise SystemExit(1)
        monkeypatch.setattr(devpi_server.views, "abort", recorder)
        return l

    def test_getjson(self):
        from devpi_server.views import getjson
        from pyramid.request import Request
        request = Request({}, body=b'{"hello": "world"}')
        assert getjson(request)["hello"] == "world"

    def test_getjson_error(self, abort_calls):
        from devpi_server.views import getjson
        from pyramid.request import Request
        request = Request({}, body=b"123 123")
        with pytest.raises(SystemExit):
            getjson(request)
        assert len(abort_calls) == 1
        abort_call_args = abort_calls[0][0]
        assert abort_call_args[1] == 400

    def test_getjson_wrong_keys(self, abort_calls):
        from devpi_server.views import getjson
        from pyramid.request import Request
        request = Request({}, body=b'{"k1": "v1", "k2": "v2"')
        with pytest.raises(SystemExit):
            getjson(request, allowed_keys=["k1", "k3"])
        assert len(abort_calls) == 1
        abort_call_args = abort_calls[0][0]
        assert abort_call_args[1] == 400


class TestTweenKeyfsTransaction:
    def test_nowrite(self, xom, blank_request):
        cur_serial = xom.keyfs.get_current_serial()
        wrapped_handler = lambda r: Response("")
        handler = tween_keyfs_transaction(wrapped_handler, {"xom": xom})
        response = handler(blank_request())
        assert response.headers.get("X-DEVPI-SERIAL") == str(cur_serial)

    def test_write(self, xom, blank_request):
        cur_serial = xom.keyfs.get_current_serial()
        def wrapped_handler(request):
            with xom.keyfs.USER(user="hello").update():
                pass
            return Response("")
        handler = tween_keyfs_transaction(wrapped_handler, {"xom": xom})
        response = handler(blank_request(method="PUT"))
        assert response.headers.get("X-DEVPI-SERIAL") == str(cur_serial + 1)

    def test_restart(self, xom, blank_request):
        cur_serial = xom.keyfs.get_current_serial()
        def wrapped_handler(request):
            xom.keyfs.restart_as_write_transaction()
            with xom.keyfs.USER(user="hello").update():
                pass
            return Response("")
        handler = tween_keyfs_transaction(wrapped_handler, {"xom": xom})
        response = handler(blank_request())
        assert response.headers.get("X-DEVPI-SERIAL") == str(cur_serial + 1)


@pytest.mark.parametrize("restrict_modify", ["admin", ":admins"])
class TestRestrictModify:
    logins = [("root",), ("regular", "regular"), ("hello", "password")]

    @pytest.fixture
    def plugin(self):
        class Plugin:
            def devpiserver_auth_user(self, userdict, username, password):
                if username == "regular" and password == "regular":
                    return dict(status="ok", groups=["regulars"])
                if username == "admin" and password == "admin":
                    return dict(status="ok", groups=["admins"])
                return dict(status="unknown")
        return Plugin()

    @pytest.fixture
    def xom(self, makexom, plugin, restrict_modify):
        xom = makexom(plugins=[plugin])
        xom.config.args.restrict_modify = restrict_modify
        return xom

    def test_create_new_user(self, mapp):
        mapp.create_user("hello", "password", code=403)
        mapp.login("root")
        mapp.create_user("hello", "password", code=403)
        mapp.login("regular", "regular")
        mapp.create_user("hello", "password", code=403)
        mapp.login("admin", "admin")
        assert "hello" not in mapp.getuserlist()
        mapp.create_user("hello", "password")
        assert "hello" in mapp.getuserlist()

    def test_modify_user(self, mapp):
        mapp.login("admin", "admin")
        mapp.create_user("hello", "password")
        assert "hello" in mapp.getuserlist()
        for login in self.logins:
            mapp.login(*login)
            mapp.modify_user("hello", email="whatever", code=403)
        mapp.login("admin", "admin")
        res = mapp.getjson("/hello")["result"]
        assert res["email"] == "hello@example.com"
        mapp.modify_user("hello", email="whatever")
        res = mapp.getjson("/hello")["result"]
        assert res["email"] == "whatever"

    def test_delete_user(self, mapp):
        mapp.login("admin", "admin")
        mapp.create_user("hello", "password")
        for login in self.logins:
            mapp.login(*login)
            mapp.delete_user("hello", code=403)
        mapp.login("admin", "admin")
        assert "hello" in mapp.getuserlist()
        mapp.delete_user("hello")
        assert "hello" not in mapp.getuserlist()

    def test_create_new_index(self, mapp):
        mapp.login("admin", "admin")
        mapp.create_user("hello", "password")
        for login in self.logins:
            mapp.login(*login)
            mapp.create_index("hello/dev", code=403)
        mapp.login("admin", "admin")
        assert "hello/dev" not in mapp.getindexlist("hello")
        mapp.create_index("hello/dev")
        assert "hello/dev" in mapp.getindexlist("hello")

    def test_modify_index(self, mapp):
        mapp.login("admin", "admin")
        mapp.create_user("hello", "password")
        mapp.create_index("hello/dev")
        for login in self.logins:
            mapp.login(*login)
            res = mapp.getjson("/hello/dev")["result"]
            mapp.modify_index("hello/dev", res, code=403)
        mapp.login("admin", "admin")
        assert res["volatile"] is True
        res["volatile"] = False
        mapp.modify_index("hello/dev", res)
        res = mapp.getjson("/hello/dev")["result"]
        assert res["volatile"] is False

    def test_delete_index(self, mapp):
        mapp.login("admin", "admin")
        mapp.create_user("hello", "password")
        mapp.create_index("hello/dev")
        for login in self.logins:
            mapp.login(*login)
            mapp.delete_index("hello/dev", code=403)
        mapp.login("admin", "admin")
        assert "hello/dev" in mapp.getindexlist("hello")
        mapp.delete_index("hello/dev")
        assert "hello/dev" not in mapp.getindexlist("hello")
