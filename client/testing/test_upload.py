import os, sys
import py
import pytest
import types
from devpi.upload.upload import (setversion, Checkout, find_parent_subpath)
from devpi.util import version as verlib
from textwrap import dedent

from devpi.main import check_output

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



class TestCheckout:
    @pytest.fixture(scope="class")
    def repo(self, request):
        repo = request.config._tmpdirhandler.mktemp("repo", numbered=True)
        file = repo.join("file")
        file.write("hello")
        repo.ensure("setup.py")
        old = repo.chdir()
        try:
            runproc("hg init")
            runproc("hg add file setup.py")
            runproc("hg commit -m message")
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

    def test_export_attributes(self, uploadhub, repo, tmpdir):
        checkout = Checkout(uploadhub, repo)
        repo.join("setup.py").write("print 'xyz-1.2.3'")
        exported = checkout.export(tmpdir)
        assert exported.setup_fullname() == "xyz-1.2.3"
        name, version = exported.name_and_version()
        assert name == "xyz"
        assert str(version) == "1.2.3"

    def test_export_changeversions(self, uploadhub, repo, tmpdir):
        checkout = Checkout(uploadhub, repo)
        repo.join("setup.py").write(dedent("""
            version = __version__ = "1.2.dev1"
            print ("pkg-%s" % version)
        """))
        exported = checkout.export(tmpdir)
        newver = verlib.Version("1.2.dev1").autoinc()
        exported.change_versions(newver, ["setup.py"])
        n,v = exported.name_and_version()
        assert newver == v
        s1 = exported.rootpath.join("setup.py").read()
        s2 = checkout.rootpath.join("setup.py").read()
        assert s1 == s2

    def test_detect_versionfiles(self, uploadhub, repo, tmpdir):
        checkout = Checkout(uploadhub, repo)
        exported = checkout.export(tmpdir)
        p = exported.rootpath.ensure("a", "__init__.py")
        p.write("__version__ = '1.2'")
        l = exported.detect_versioncandidates()
        assert p.relto(exported.rootpath) in l


def test_parent_subpath(tmpdir):
    s = tmpdir.ensure("xyz")
    assert find_parent_subpath(tmpdir.mkdir("a"), "xyz") == s
    assert find_parent_subpath(tmpdir.ensure("a", "b"), "xyz") == s
    assert find_parent_subpath(s, "xyz") == s
    pytest.raises(ValueError, lambda: find_parent_subpath(tmpdir, "poiqel123"))

def test_setversion():
    content = "\n".join([
        "x=__version__",
        "version = __version__='1.3.0.dev0'"
    ])
    expected = content.replace("1.3.0.dev0", "1.3.0a1").strip()
    s = setversion(content, "1.3.0a1")
    assert s.strip() == expected

    content = "\n".join([
        "x=__version__",
        "__version__ = '1.3.0.dev0'"
    ])
    s = setversion(content, "1.3.0a5").strip()
    assert s == content.replace("1.3.0.dev0", "1.3.0a5").strip()

def test_readpypirc(monkeypatch, tmpdir):
    from devpi.upload.setuppy import _prepare_distutils
    from distutils.config import PyPIRCCommand
    monkeypatch.setattr(sys, "argv", ["xxx", str(tmpdir), "http://something",
                                      "user", "password",
                                      "register", "1"])
    _prepare_distutils()
    cmd = types.InstanceType(PyPIRCCommand)
    current = PyPIRCCommand._read_pypirc(cmd)
    assert current["server"] == "devpi"
    assert current["repository"] == "http://something"
    assert current["username"] == "user"
    assert current["password"] == "password"
    assert current["realm"] == "pypi"
    assert sys.argv == ["setup.py", "register", "1"]

class TestUploadFunctional:
    def test_dryrun_all(self, initproj, devpi):
        initproj("hello-1.0", {"doc": {
            "conf.py": "",
            "index.html": "<html/>"}})
        assert py.path.local("setup.py").check()
        devpi("upload", "--dryrun")
        devpi("upload", "--dryrun", "--withdocs")
        devpi("upload", "--dryrun", "--onlydocs")
        devpi("upload", "--formats", "sdist.tbz")
        devpi("upload", "--formats", "sdist.tgz,bdist_dumb")

