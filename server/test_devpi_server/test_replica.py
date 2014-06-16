import pytest
import py
from devpi_server.replica import *
from devpi_common.url import URL

def loads(bytestring):
    return load(py.io.BytesIO(bytestring))

pytestmark = [pytest.mark.notransaction]

def test_view_name2serials(pypistage, testapp):
    pypistage.mock_simple("package", '<a href="/package-1.0.zip" />',
                          pypiserial=15)
    r = testapp.get("/root/pypi/+name2serials", expect_errors=False)
    io = py.io.BytesIO(r.body)
    entries = load(io)
    assert entries["package"] == 15


class TestChangelog:
    def get_latest_serial(self, testapp):
        r = testapp.get("/+changelog/nop", expect_errors=False)
        return int(r.headers["X-DEVPI-SERIAL"])

    def test_get_latest_serial(self, testapp, mapp):
        latest_serial = self.get_latest_serial(testapp)
        assert latest_serial >= -1
        mapp.create_user("hello", "pass")
        assert self.get_latest_serial(testapp) == latest_serial + 1

    def test_get_since(self, testapp, mapp, noiter):
        mapp.create_user("this", password="p")
        latest_serial = self.get_latest_serial(testapp)
        r = testapp.get("/+changelog/%s" % latest_serial, expect_errors=False)
        body = b''.join(r.app_iter)
        data = loads(body)
        assert "this" in str(data)

    def test_get_wait(self, testapp, mapp, noiter, monkeypatch):
        mapp.create_user("this", password="p")
        latest_serial = self.get_latest_serial(testapp)
        monkeypatch.setattr(testapp.xom.keyfs.notifier.cv_new_transaction,
                            "wait", lambda *x: 0/0)
        with pytest.raises(ZeroDivisionError):
            testapp.get("/+changelog/%s" % (latest_serial+1,),
                        expect_errors=False)


class TestPyPIProxy:
    def test_pypi_proxy(self, xom, reqmock):
        from devpi_server.keyfs import dump
        url = "http://localhost:3141/root/pypi/+name2serials"
        master_url = URL("http://localhost:3141")
        proxy = PyPIProxy(xom._httpsession, master_url)
        io = py.io.BytesIO()
        dump({"hello": 42}, io)
        data = io.getvalue()
        reqmock.mockresponse(url=url, code=200, method="GET", data=data)
        name2serials = proxy.list_packages_with_serial()
        assert name2serials == {"hello": 42}

    def test_replica_startup(self, replica_xom):
        assert isinstance(replica_xom.proxy, PyPIProxy)


def test_pypi_project_changed(replica_xom):
    handler = PypiProjectChanged(replica_xom)
    class Ev:
        value = dict(projectname="newproject", serial=12)
        typedkey = replica_xom.keyfs.get_key("PYPILINKS")
    handler(Ev())
    assert replica_xom.pypimirror.name2serials["newproject"] == 12
    class Ev2:
        value = dict(projectname="newproject", serial=15)
        typedkey = replica_xom.keyfs.get_key("PYPILINKS")
    handler(Ev2())
    assert replica_xom.pypimirror.name2serials["newproject"] == 15

class TestReplicaThread:
    @pytest.fixture
    def rt(self, makexom):
        xom = makexom(["--master=http://localhost"])
        rt = ReplicaThread(xom)
        xom.thread_pool.register(rt)
        return rt

    def test_thread_run_fail(self, rt, reqmock, caplog):
        rt.thread.sleep = lambda x: 0/0
        reqmock.mockresponse("http://localhost/+changelog/1", code=404)
        with pytest.raises(ZeroDivisionError):
            rt.thread_run()
        assert caplog.getrecords("404.*failed fetching*")

    def test_thread_run_decode_error(self, rt, reqmock, caplog):
        rt.thread.sleep = lambda x: 0/0
        reqmock.mockresponse("http://localhost/+changelog/1", code=200,
                             data=b'qlwekj')
        with pytest.raises(ZeroDivisionError):
            rt.thread_run()
        assert caplog.getrecords("could not read answer")

    def test_thread_run_ok(self, rt, reqmock, caplog):
        rt.thread.sleep = rt.thread.exit_if_shutdown = lambda *x: 0/0
        reqmock.mockresponse("http://localhost/+changelog/1", code=200,
                             data=rt.xom.keyfs._fs.get_raw_changelog_entry(0))
        with pytest.raises(ZeroDivisionError):
            rt.thread_run()
        assert caplog.getrecords("committed")

class TestTweenReplica:
    def test_nowrite(self, xom, blank_request):
        l = []
        def wrapped_handler(request):
            l.append(xom.keyfs.get_current_serial())
            return Response("")
        handler = tween_replica_proxy(wrapped_handler, {"xom": xom})
        handler(blank_request())
        assert l == [xom.keyfs.get_current_serial()]

    def test_write_proxies(self, makexom, blank_request, reqmock, monkeypatch):
        xom = makexom(["--master", "http://localhost"])
        reqmock.mock("http://localhost/blankpath",
                     code=200, headers={"X-DEVPI-SERIAL": "10"})
        l = []
        monkeypatch.setattr(xom.keyfs.notifier, "wait_tx_serial",
                            lambda x: l.append(x))
        handler = tween_replica_proxy(None, {"xom": xom})
        response = handler(blank_request(method="PUT"))
        assert response.headers.get("X-DEVPI-SERIAL") == "10"
        assert l == [10]


def test_cache_remote_file_fails(makexom, gen, monkeypatch):
    xom = makexom(["--master", "http://localhost"])
    l = []
    monkeypatch.setattr(xom.keyfs.notifier, "wait_tx_serial",
                        lambda x: l.append(x))
    with xom.keyfs.transaction(write=True):
        link = gen.pypi_package_link("pytest-1.8.zip", md5=True)
        entry = xom.filestore.maplink(link)
        assert entry.md5 and not entry.file_exists()
    with xom.keyfs.transaction():
        headers={"content-length": "3",
                 "last-modified": "Thu, 25 Nov 2010 20:00:27 GMT",
                 "content-type": "application/zip",
                 "X-DEVPI-SERIAL": "10"}
        url = xom.config.master_url.joinpath(entry.relpath).url
        xom.httpget.mockresponse(url, status_code=200,
                    headers=headers, raw = py.io.BytesIO(b"123"))
        with pytest.raises(ValueError):
            newentry = entry.cache_remote_file_replica()
