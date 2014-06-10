import pytest
import py
from devpi_server.replica import *

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


class TestPyPIProxy:
    def test_pypi_proxy(self, xom, reqmock):
        from devpi_server.keyfs import dump
        url = "http://localhost:3141/root/pypi/+name2serials"
        master_url = "http://localhost:3141"
        proxy = PyPIProxy(xom, master_url)
        io = py.io.BytesIO()
        dump({"hello": 42}, io)
        data = io.getvalue()
        rec = reqmock.mockresponse(url=url, code=200, method="GET", data=data)
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
