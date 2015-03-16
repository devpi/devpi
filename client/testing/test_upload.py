
import os, sys
import json
import py
import pytest
from devpi.upload import *
from textwrap import dedent
from devpi_common.metadata import splitbasename
from devpi_common.viewhelp import ViewLinkStore
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
#    monkeypatch.setattr(extpypi.ExtDB, "get_releaselinks", lambda *args: 404)


class TestCheckout:
    @pytest.fixture(autouse=True)
    def no_sys_executable(self, monkeypatch):
        """ make sure sys.executable is not used accidentally. """
        monkeypatch.setattr(sys, "executable", None)

    @pytest.fixture(scope="class", params=["hg", "git"])
    def repo(self, request):
        repo = request.config._tmpdirhandler.mktemp("repo", numbered=True)
        file = repo.join("file")
        file.write("hello")
        repo.ensure("setup.py")
        # this is a test for issue154 although we actually don't really
        # need to test the vcs-exporting code much since we started
        # relying on the external check-manifest project to do things.
        unicode_fn = b"something-\342\200\223.txt"
        if sys.version_info >= (3,0):
            unicode_fn = str(unicode_fn, "utf8")
        repo.ensure(unicode_fn)
        if request.param == "hg":
            if not py.path.local.sysfind("hg"):
                pytest.skip("'hg' command not found")
            with repo.as_cwd():
                runproc("hg init")
                runproc("hg add file setup.py")
                runproc("hg add file %s" % unicode_fn)
                runproc("hg commit --config ui.username=whatever -m message")
            return repo
        if not py.path.local.sysfind("git"):
            pytest.skip("'git' command not found")
        with repo.as_cwd():
            runproc("git init")
            runproc("git config user.email 'you@example.com'")
            runproc("git config user.name 'you'")
            runproc("git add file setup.py")
            runproc("git add file %s" % unicode_fn)
            runproc("git commit -m message")
        return repo

    def test_vcs_export(self, uploadhub, repo, tmpdir, monkeypatch):
        checkout = Checkout(uploadhub, repo)
        assert checkout.rootpath == repo
        newrepo = tmpdir.mkdir("newrepo")
        result = checkout.export(newrepo)
        assert result.rootpath.join("file").check()
        assert result.rootpath == newrepo.join(repo.basename)

    def test_vcs_export_disabled(self, uploadhub, repo, tmpdir, monkeypatch):
        monkeypatch.setattr(uploadhub.args, "novcs", True)
        checkout = Checkout(uploadhub, repo)
        assert not checkout.hasvcs
        exported = checkout.export(tmpdir)
        assert exported.rootpath == checkout.rootpath

    def test_vcs_export_verify_setup(self, uploadhub, repo,
                                          tmpdir, monkeypatch):
        subdir = repo.mkdir("subdir")
        subdir.ensure("setup.py")
        checkout = Checkout(uploadhub, subdir)
        wc = tmpdir.mkdir("wc")
        exported = checkout.export(wc)
        with pytest.raises(SystemExit):
            exported.check_setup()

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


# this class is necessary, because the tox initproj fixture doesn't
# support names like this (yet)
class NameHack:
    def __init__(self, name, version):
        self.name = name
        self.version = version

    def split(self, sep):
        assert sep == '-'
        return self.name, self.version

    def __str__(self):
        return "%s-%s" % (self.name, self.version)


class TestUploadFunctional:
    @pytest.mark.parametrize("projname_version", [
        "hello-1.0", NameHack("my-pkg-123", "1.0")])
    def test_all(self, initproj, devpi, out_devpi, projname_version):
        initproj(projname_version, {"doc": {
            "conf.py": "#nothing",
            "index.html": "<html/>"}})
        assert py.path.local("setup.py").check()
        out = out_devpi("upload", "--dry-run")
        assert out.ret == 0
        out.stdout.fnmatch_lines("""
            built:*
            skipped: file_upload of {projname_version}.*
            """.format(projname_version=projname_version))
        out = out_devpi("upload", "--dry-run", "--with-docs")
        assert out.ret == 0
        out.stdout.fnmatch_lines("""
            built:*
            skipped: file_upload of {projname_version}.*
            skipped: doc_upload of {projname_version}.doc.zip*
            """.format(projname_version=projname_version))
        out = out_devpi("upload", "--dry-run", "--only-docs")
        assert out.ret == 0
        out.stdout.fnmatch_lines("""
            built:*
            skipped: doc_upload of {projname_version}.doc.zip*
            """.format(projname_version=projname_version))
        out = out_devpi("upload", "--with-docs", code=[200,200,200])
        assert out.ret == 0
        out.stdout.fnmatch_lines("""
            built:*
            file_upload of {projname_version}.*
            doc_upload of {projname_version}.doc.zip*
            """.format(projname_version=projname_version))
        out = out_devpi("upload", "--formats", "sdist.zip", code=[200,200])
        assert out.ret == 0
        out.stdout.fnmatch_lines("""
            built:*
            file_upload of {projname_version}.zip*
            """.format(projname_version=projname_version))
        out = out_devpi("upload", "--formats", "sdist.zip,bdist_dumb",
                        code=[200, 200, 200, 200])
        out.stdout.fnmatch_lines_random("""
            file_upload of {projname_version}.*
            file_upload of {projname_version}.zip*
            """.format(projname_version=projname_version))

        # logoff then upload
        devpi("logoff")
        devpi("upload", "--dry-run")

        # go to other index
        devpi("use", "root/pypi")
        devpi("upload", "--dry-run")

        # see if we get an error return code
        res = devpi("upload")
        assert isinstance(res.sysex, SystemExit)
        assert res.sysex.args == (1,)

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
            url = hub.current.get_index_url().url + "hello/%s/" % ver
            out = out_devpi("getjson", url)
            data = json.loads(out.stdout.str())
            vv = ViewLinkStore(url, data["result"])
            assert vv.get_link(basename="hello-%s.zip" % ver)

    def test_frompath(self, initproj, devpi, out_devpi, runproc):
        from devpi_common.archive import zip_dir
        initproj("hello-1.3", {"doc": {
            "conf.py": "",
            "index.html": "<html/>"}})
        tmpdir = py.path.local()
        runproc(tmpdir, "python setup.py sdist --format=zip".split())
        bpath = tmpdir.join('build')
        out = runproc(
            tmpdir,
            "python setup.py build_sphinx -E --build-dir".split() + [bpath.strpath])
        dist = tmpdir.join("dist")
        zip_dir(bpath.join('html'), dist.join("hello-1.3.doc.zip"))
        assert len(dist.listdir()) == 2
        (p, dp) = sorted(dist.listdir(), key=lambda x: '.doc.zip' in x.basename)
        hub = devpi("upload", p, dp)
        path = "hello/1.3/"
        url = hub.current.get_index_url().url + path
        out = out_devpi("getjson", url)
        data = json.loads(out.stdout.str())
        vv = ViewLinkStore(url, data["result"])
        assert vv.get_link(basename="hello-1.3.zip")
        assert vv.get_link(basename="hello-1.3.doc.zip")

    def test_frompath_complex_name(self, initproj, devpi, out_devpi, runproc):
        from devpi_common.archive import zip_dir
        initproj(NameHack("my-pkg-123", "1.3"), {"doc": {
            "conf.py": "",
            "index.html": "<html/>"}})
        tmpdir = py.path.local()
        runproc(tmpdir, "python setup.py sdist --format=zip".split())
        bpath = tmpdir.join('build')
        out = runproc(
            tmpdir,
            "python setup.py build_sphinx -E --build-dir".split() + [bpath.strpath])
        dist = tmpdir.join("dist")
        zip_dir(bpath.join('html'), dist.join("my-pkg-123-1.3.doc.zip"))
        assert len(dist.listdir()) == 2
        (p, dp) = sorted(dist.listdir(), key=lambda x: '.doc.zip' in x.basename)
        hub = devpi("upload", p, dp)
        path = "my-pkg-123/1.3/"
        url = hub.current.get_index_url().url + path
        out = out_devpi("getjson", url)
        data = json.loads(out.stdout.str())
        vv = ViewLinkStore(url, data["result"])
        assert vv.get_link(basename="my-pkg-123-1.3.zip")
        assert vv.get_link(basename="my-pkg-123-1.3.doc.zip")



def test_getpkginfo(datadir):
    info = get_pkginfo(datadir.join("dddttt-0.1.dev45-py27-none-any.whl"))
    assert info.name == "dddttt"
    assert info.metadata_version == "2.0"
    info = get_pkginfo(datadir.join("ddd-1.0.doc.zip"))
    assert info.name == "ddd"
    assert info.version == "1.0"

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


