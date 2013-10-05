import os, sys
import json
import py
import pytest
import types
from devpi.upload.upload import *
from textwrap import dedent
from devpi_common.s_url import splitbasename

from devpi.main import check_output

@pytest.fixture
def datadir():
    return py.path.local(__file__).dirpath("data")

def runproc(cmd):
    args = cmd.split()
    path0 = args[0]
    if not os.path.isabs(path0):
        path0 = py.path.local.sysfind(path0)
        if not path0:
            pytest.skip("%r not found" % args[0])
    return check_output([str(path0)] + args[1:])

@pytest.fixture
def uploadhub(request, tmpdir):
    from devpi.main import initmain
    hub, method = initmain(["devpitest",
                           "--clientdir", tmpdir.join("client").strpath,
                           "upload"])
    return hub

#@pytest.fixture(autouse=True)
#def extpypi_404(monkeypatch):
#    from devpi_server import extpypi  # this is only client side
#    monkeypatch.setattr(extpypi.ExtDB, "getreleaselinks", lambda *args: 404)


class TestCheckout:
    @pytest.fixture(autouse=True)
    def no_sys_executable(self, monkeypatch):
        """ make sure sys.executable is not used accidentally. """
        monkeypatch.setattr(sys, "executable", None)

    @pytest.fixture(scope="class")
    def repo(self, request):
        if not py.path.local.sysfind("hg"):
            pytest.skip("'hg' command not found")
        repo = request.config._tmpdirhandler.mktemp("repo", numbered=True)
        file = repo.join("file")
        file.write("hello")
        repo.ensure("setup.py")
        old = repo.chdir()
        try:
            runproc("hg init")
            runproc("hg add file setup.py")
            runproc("hg commit --config ui.username=whatever -m message")
        finally:
            old.chdir()
        return repo

    def test_hg_export(self, uploadhub, repo, tmpdir, monkeypatch):
        checkout = Checkout(uploadhub, repo)
        assert checkout.rootpath == repo
        newrepo = tmpdir.mkdir("newrepo")
        result = checkout.export(newrepo)
        assert result.rootpath.join("file").check()
        assert result.rootpath == newrepo.join(repo.basename)

    def test_hg_export_disabled(self, uploadhub, repo, tmpdir, monkeypatch):
        monkeypatch.setattr(uploadhub.args, "novcs", True)
        checkout = Checkout(uploadhub, repo)
        assert not checkout.hashg

    def test_hg_export_verify_setup(self, uploadhub, repo,
                                          tmpdir, monkeypatch):
        subdir = repo.mkdir("subdir")
        subdir.ensure("setup.py")
        checkout = Checkout(uploadhub, subdir)
        wc = tmpdir.mkdir("wc")
        exported = checkout.export(wc)
        with pytest.raises(SystemExit):
            exported.check_setup()
        with pytest.raises(SystemExit):
            exported.setup_register()
        with pytest.raises(SystemExit):
            exported.setup_upload()

    def test_export_attributes(self, uploadhub, repo, tmpdir, monkeypatch):
        checkout = Checkout(uploadhub, repo)
        repo.join("setup.py").write(dedent("""
            from setuptools import setup
            setup(name="xyz", version="1.2.3")
        """))
        exported = checkout.export(tmpdir)
        name, version = exported.setup_name_and_version()
        assert name == "xyz"
        assert version == "1.2.3"


def test_parent_subpath(tmpdir):
    s = tmpdir.ensure("xyz")
    assert find_parent_subpath(tmpdir.mkdir("a"), "xyz") == s
    assert find_parent_subpath(tmpdir.ensure("a", "b"), "xyz") == s
    assert find_parent_subpath(s, "xyz") == s
    pytest.raises(ValueError, lambda: find_parent_subpath(tmpdir, "poiqel123"))

def test_readpypirc(monkeypatch, tmpdir):
    from devpi.upload.setuppy import _prepare_distutils
    from distutils.config import PyPIRCCommand
    monkeypatch.setattr(sys, "argv", ["xxx", str(tmpdir), "http://something",
                                      "user", "password",
                                      "register", "1"])
    assert str(tmpdir) not in sys.path
    _prepare_distutils()
    assert str(tmpdir) in sys.path
    cmd = types.InstanceType(PyPIRCCommand)
    current = PyPIRCCommand._read_pypirc(cmd)
    assert current["server"] == "devpi"
    assert current["repository"] == "http://something"
    assert current["username"] == "user"
    assert current["password"] == "password"
    assert current["realm"] == "pypi"
    assert sys.argv == ["setup.py", "register", "1"]

def test_setuppy_execution_namespace(monkeypatch, tmpdir):
    from devpi.upload.setuppy import run_setuppy
    def mockexecfile(filename, global_ns, local_ns=None):
        assert global_ns["__file__"] == os.path.join(str(tmpdir), "setup.py")
    monkeypatch.setattr(py.builtin.builtins, 'execfile', mockexecfile)
    tmpdir.chdir()
    run_setuppy()

class TestUploadFunctional:
    def test_all(self, initproj, devpi):
        initproj("hello-1.0", {"doc": {
            "conf.py": "",
            "index.html": "<html/>"}})
        assert py.path.local("setup.py").check()
        devpi("upload", "--dry-run")
        devpi("upload", "--dry-run", "--with-docs")
        devpi("upload", "--dry-run", "--only-docs")
        devpi("upload", "--formats", "sdist.zip")
        devpi("upload", "--formats", "sdist.tgz,bdist_dumb")

        # logoff then upload
        devpi("logoff")
        devpi("upload", "--dry-run")

        # go to other index
        devpi("use", "root/pypi")
        devpi("upload", "--dry-run")

    def test_fromdir(self, initproj, devpi, out_devpi, runproc, monkeypatch):
        initproj("hello-1.1", {"doc": {
            "conf.py": "",
            "index.html": "<html/>"}})
        tmpdir = py.path.local()
        runproc(tmpdir, "python setup.py sdist --format=zip".split())
        initproj("hello-1.2")
        runproc(tmpdir, "python setup.py sdist --format=zip".split())
        dist = tmpdir.join("dist")
        assert len(dist.listdir()) == 2
        hub = devpi("upload", "--from-dir", dist)
        for ver in ("1.1", '1.2'):
            out = out_devpi("getjson", hub.current.index + "hello/%s/" % ver)
            data = json.loads(out.stdout.str())
            assert ("hello-%s.zip" % ver) in data["result"]["+files"]

    def test_frompath(self, initproj, devpi, out_devpi, runproc):
        initproj("hello-1.3", {"doc": {
            "conf.py": "",
            "index.html": "<html/>"}})
        tmpdir = py.path.local()
        runproc(tmpdir, "python setup.py sdist --format=zip".split())
        dist = tmpdir.join("dist")
        assert len(dist.listdir()) == 1
        p = dist.listdir()[0]
        hub = devpi("upload", p)
        out = out_devpi("getjson", hub.current.index + "hello/1.3/")
        data = json.loads(out.stdout.str())
        assert "hello-1.3.zip" in data["result"]["+files"]



def test_getpkginfo(datadir):
    info = get_pkginfo(datadir.join("dddttt-0.1.dev45-py27-none-any.whl"))
    assert info.name == "dddttt"
    assert info.metadata_version == "2.0"


def test_filter_latest():
    class PkgInfo(object):
        def __init__(self, path):
            self.name, self.version = splitbasename(path + ".zip")[:2]

    d = {}
    for idx in [1, 9, 10]:
        path = 'test-abc-0.%d' % (idx)
        d[path] = PkgInfo(path)
    assert len(d) == 3
    d = filter_latest(d)
    assert len(d) == 1
    filtered = d[path]
    assert filtered.name == 'test-abc'
    assert filtered.version == u'0.10'



