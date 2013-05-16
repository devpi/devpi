import sys
import pytest
import types
from devpi.upload.upload import (setversion, Checkout, find_parent_subpath)
from devpi.util import version as verlib
from textwrap import dedent

from subprocess import check_call, Popen, check_output

def runproc(cmd):
    args = cmd.split()
    return check_output(args)

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

    def test_hg_export(self, emptyhub, repo, tmpdir, monkeypatch):
        checkout = Checkout(emptyhub, repo.join("file"))
        assert checkout.rootpath == repo
        newrepo = tmpdir.mkdir("newrepo")
        result = checkout.export(newrepo)
        assert result.rootpath.join("file").check()
        assert result.rootpath == newrepo.join(repo.basename)

    def test_export_attributes(self, emptyhub, repo, tmpdir):
        checkout = Checkout(emptyhub, repo)
        repo.join("setup.py").write("print 'xyz-1.2.3'")
        exported = checkout.export(tmpdir)
        assert exported.setup_fullname() == "xyz-1.2.3"
        name, version = exported.name_and_version()
        assert name == "xyz"
        assert str(version) == "1.2.3"

    def test_export_changeversions(self, emptyhub, repo, tmpdir):
        checkout = Checkout(emptyhub, repo)
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

    def test_detect_versionfiles(self, emptyhub, repo, tmpdir):
        checkout = Checkout(emptyhub, repo)
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
                                      "register", "1"])
    _prepare_distutils()
    cmd = types.InstanceType(PyPIRCCommand)
    current = PyPIRCCommand._read_pypirc(cmd)
    assert current["server"] == "devpiindex"
    assert current["repository"] == "http://something"
    assert sys.argv == ["setup.py", "register", "1"]

