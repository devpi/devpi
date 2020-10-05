import json
import os
import py
import pytest
import re
import sys
from devpi.upload import Checkout
from devpi.upload import find_parent_subpath
from devpi.upload import filter_latest
from devpi.upload import get_pkginfo
from devpi.upload import main
from devpi.upload import read_setupcfg
from textwrap import dedent
from devpi_common.metadata import splitbasename
from devpi_common.viewhelp import ViewLinkStore
from subprocess import check_output


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


@pytest.mark.skipif("config.option.fast")
class TestCheckout:
    @pytest.fixture(autouse=True)
    def no_sys_executable(self, monkeypatch):
        """ make sure sys.executable is not used accidentally. """
        monkeypatch.setattr(sys, "executable", None)

    @pytest.fixture(scope="class", params=[".", "setupdir"])
    def setupdir_rel(self, request):
        return request.param

    @pytest.fixture(scope="class")
    def setupdir(self, repo, setupdir_rel):
        return repo.join(setupdir_rel)

    @pytest.fixture(scope="class", params=["hg", "git"])
    def repo(self, request, setupdir_rel, tmpdir_factory):
        repo = tmpdir_factory.mktemp("repo", numbered=True)
        setupdir = repo.ensure_dir(setupdir_rel)
        file = setupdir.join("file")
        file.write("hello")
        link = setupdir.join("link")
        setup_path = setupdir.ensure("setup.py")
        if not sys.platform.startswith("win"):
            setup_path.chmod(int("0777", 8))
            link.mksymlinkto("..", absolute=True)
        else:
            link.write("no symlinks on windows")

        # this is a test for issue154 although we actually don't really
        # need to test the vcs-exporting code much since we started
        # relying on the external check-manifest project to do things.
        unicode_fn = b"something-\342\200\223.txt"
        if sys.version_info >= (3,0):
            unicode_fn = str(unicode_fn, "utf8")
        setupdir.ensure(unicode_fn)
        if request.param == "hg":
            if not py.path.local.sysfind("hg"):
                pytest.skip("'hg' command not found")
            with repo.as_cwd():
                runproc("hg init")
                runproc("hg add {0}/file {0}/link {0}/setup.py".format(setupdir_rel))
                runproc("hg add {0}/file {0}/{1}".format(setupdir_rel,
                                                         unicode_fn))
                runproc("hg commit --config ui.username=whatever -m message")
            return repo
        if not py.path.local.sysfind("git"):
            pytest.skip("'git' command not found")
        with repo.as_cwd():
            runproc("git init")
            runproc("git config user.email 'you@example.com'")
            runproc("git config user.name 'you'")
            runproc("git add {0}/file {0}/link {0}/setup.py".format(setupdir_rel))
            runproc("git add {0}/file {0}/{1}".format(setupdir_rel,
                                                      unicode_fn))
            runproc("git commit -m message")
        return repo

    def test_vcs_export(self, uploadhub, repo, setupdir, tmpdir, monkeypatch):
        checkout = Checkout(uploadhub, setupdir)
        assert checkout.rootpath == repo
        newrepo = tmpdir.mkdir("newrepo")
        result = checkout.export(newrepo)
        assert result.rootpath.join("file").check()
        assert result.rootpath.join("link").check()
        if not sys.platform.startswith("win"):
            assert result.rootpath.join("link").readlink() == ".."
        assert result.rootpath == newrepo.join(repo.basename).join(
            repo.bestrelpath(setupdir))
        # ensure we also copied repo meta info
        if repo.join(".hg").exists():
            assert newrepo.join(repo.basename).join(".hg").listdir()
        else:
            assert newrepo.join(repo.basename).join(".git").listdir()

    def test_vcs_export_setupdironly(self, uploadhub, setupdir,
                                          tmpdir, monkeypatch):
        monkeypatch.setattr(uploadhub.args, "setupdironly", True)
        checkout = Checkout(uploadhub, setupdir)
        assert checkout.rootpath == setupdir
        newrepo = tmpdir.mkdir("newrepo")
        result = checkout.export(newrepo)
        assert result.rootpath.join("file").check()
        assert result.rootpath.join("link").check()
        p = result.rootpath.join("setup.py")
        assert p.exists()
        if not sys.platform.startswith("win"):
            assert p.stat().mode & int("0777", 8) == int("0777", 8)
            assert result.rootpath.join("link").readlink() == '..'
        assert result.rootpath == newrepo.join(setupdir.basename)

    def test_vcs_export_disabled(self, uploadhub, setupdir,
                                      tmpdir, monkeypatch):
        monkeypatch.setattr(uploadhub.args, "novcs", True)
        checkout = Checkout(uploadhub, setupdir)
        assert not checkout.hasvcs
        exported = checkout.export(tmpdir)
        assert exported.rootpath == checkout.setupdir

    def test_vcs_export_verify_setup(self, uploadhub, setupdir,
                                          tmpdir, monkeypatch):
        subdir = setupdir.mkdir("subdir")
        subdir.ensure("setup.py")
        checkout = Checkout(uploadhub, subdir)
        wc = tmpdir.mkdir("wc")
        exported = checkout.export(wc)
        with pytest.raises(SystemExit):
            exported.check_setup()

    def test_export_attributes(self, uploadhub, setupdir, tmpdir, monkeypatch):
        checkout = Checkout(uploadhub, setupdir)
        setupdir.join("setup.py").write(dedent("""
            from setuptools import setup
            # some packages like numpy produce output during build, simulate:
            print("* foo, bar")
            setup(name="xyz", version="1.2.3")
        """))
        exported = checkout.export(tmpdir)
        name, version = exported.setup_name_and_version()
        assert name == "xyz"
        assert version == "1.2.3"

    def test_setup_build_docs(self, uploadhub, setupdir, tmpdir, monkeypatch):
        checkout = Checkout(uploadhub, setupdir)
        setupdir.join("setup.py").write(dedent("""
            from setuptools import setup
            setup(name="xyz", version="1.2.3")
        """))
        exported = checkout.export(tmpdir)
        assert exported.rootpath != exported.origrepo
        # we have to mock a bit unfortunately
        # to find out if the sphinx building popen command
        # is called with the exported directory instead of he original
        l = []
        old_popen_output = exported.hub.popen_output

        def mock_popen_output(args, **kwargs):
            if "build_sphinx" in args:
                l.append(kwargs)
            else:
                return old_popen_output(args, **kwargs)

        exported.hub.popen_output = mock_popen_output
        # now we can make the call
        exported.setup_build_docs()
        assert l[0]["cwd"] == exported.rootpath


def test_setup_build_formats_setupcfg(uploadhub, tmpdir):
    tmpdir.join("setup.cfg").write(dedent("""
        [bdist_wheel]
        universal = 1

        [devpi:upload]
        formats=bdist_wheel,sdist.zip
        no-vcs=1
        setupdir-only=1
    """))
    cfg = read_setupcfg(uploadhub, tmpdir)
    assert cfg.get("formats") == "bdist_wheel,sdist.zip"
    assert cfg.get("no-vcs") == "1"
    assert cfg.get("setupdir-only") == "1"


def test_setup_build_formats_setupcfg_nosection(uploadhub, tmpdir):
    tmpdir.join("setup.cfg").write(dedent("""
        [bdist_wheel]
        universal = 1
    """))
    cfg = read_setupcfg(uploadhub, tmpdir)
    assert not cfg.get("formats")
    assert not cfg.get("no-vcs")
    assert not cfg.get("setupdir-only")


def test_parent_subpath(tmpdir):
    s = tmpdir.ensure("xyz")
    assert find_parent_subpath(tmpdir.mkdir("a"), "xyz") == s
    assert find_parent_subpath(tmpdir.ensure("a", "b"), "xyz") == s
    assert find_parent_subpath(s, "xyz") == s
    pytest.raises(ValueError, lambda: find_parent_subpath(tmpdir, "poiqel123"))


@pytest.mark.skipif("config.option.fast")
def test_post_includes_auth_info(initproj, monkeypatch, uploadhub):
    class Session:
        posts = []

        def post(self, *args, **kwargs):
            class reply:
                status_code = 200
            self.posts.append((args, kwargs))
            return reply

    class args:
        dryrun = None
        index = None
        only_latest = None
        onlydocs = None
        path = None
        withdocs = None

    initproj("pkg-1.0")
    tmpdir = py.path.local()
    certpath = tmpdir.join("cert.key").strpath
    uploadhub.cwd = tmpdir
    uploadhub.http = Session()
    uploadhub.current.reconfigure(dict(
        index="http://devpi/foo/bar",
        login="http://devpi/+login",
        pypisubmit="http://devpi/foo/bar"))
    uploadhub.current.set_auth("devpi", "password")
    uploadhub.current.set_basic_auth("basic", "auth")
    uploadhub.current.set_client_cert(certpath)
    main(uploadhub, args)
    (submit, upload) = Session.posts
    assert submit[0][1][":action"] == "submit"
    assert submit[1]["auth"] == ("basic", "auth")
    assert submit[1]["cert"] == certpath
    assert "X-Devpi-Auth" in submit[1]["headers"]
    assert upload[0][1][":action"] == "file_upload"
    assert upload[1]["auth"] == ("basic", "auth")
    assert upload[1]["cert"] == certpath
    assert "X-Devpi-Auth" in upload[1]["headers"]


class TestUploadFunctional:
    @pytest.mark.parametrize("projname_version", [
        "hello-1.0", "my-pkg-123-1.0"])
    def test_all(self, initproj, devpi, out_devpi, projname_version):
        initproj(projname_version.rsplit("-", 1), {"doc": {
            "conf.py": "#nothing",
            "contents.rst": "",
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

        print("*"*80)
        out = out_devpi("upload", "--formats", "sdist.zip,bdist_wheel",
                        code=[200, 200, 200, 200])
        out.stdout.fnmatch_lines_random("""
            file_upload of {projname_version}.*
            file_upload of {projname_version_norm}*.whl*
            """.format(projname_version=projname_version,
                       projname_version_norm=projname_version.replace("-", "*")
                       ))

        # remember username
        out = out_devpi("use")
        user = re.search(r'\(logged in as (.+?)\)', out.stdout.str()).group(1)

        # go to other index
        out = out_devpi("use", "root/pypi")
        out.stdout.fnmatch_lines_random("current devpi index*/root/pypi*")
        out = out_devpi("upload", "--dry-run")
        out.stdout.fnmatch_lines_random("*does not support upload.")
        out.stdout.fnmatch_lines_random("*it is a mirror.")

        # --index option
        out = out_devpi("upload", "--index", "%s/dev" % user, "--dry-run")
        out.stdout.fnmatch_lines_random("skipped: register*to*/%s/dev*" % user)

        # go back
        out = out_devpi("use", "%s/dev" % user)
        out.stdout.fnmatch_lines_random("current devpi index*/%s/dev*" % user)
        # logoff then upload
        out = out_devpi("logoff")
        out.stdout.fnmatch_lines_random("login information deleted")
        out = out_devpi("upload", "--dry-run")
        out.stdout.fnmatch_lines_random("need to be authenticated*")

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

    @pytest.mark.parametrize("name_version, path", [
        ("hello-1.3", "hello/1.3/"),
        (("my-pkg-123", "1.3"), "my-pkg-123/1.3/"),
        ("mypackage-1.7.3.dev304+ng04e6ea2", "mypackage/1.7.3.dev304+ng04e6ea2"),
        (("my-pkg-123", "1.7.3.dev304+ng04e6ea2"), "my-pkg-123/1.7.3.dev304+ng04e6ea2")])
    def test_frompath(self, initproj, devpi, name_version, out_devpi, path, runproc):
        from devpi_common.archive import zip_dir
        if isinstance(name_version, tuple):
            name_version_str = "%s-%s" % name_version
        else:
            name_version_str = name_version
        initproj(name_version, {"doc": {
            "conf.py": "",
            "index.html": "<html/>"}})
        tmpdir = py.path.local()
        runproc(tmpdir, "python setup.py sdist --format=zip".split())
        bpath = tmpdir.join('build')
        out = runproc(
            tmpdir,
            "python setup.py build_sphinx -E --build-dir".split() + [bpath.strpath])
        dist = tmpdir.join("dist")
        zip_dir(bpath.join('html'), dist.join("%s.doc.zip" % name_version_str))
        assert len(dist.listdir()) == 2
        (p, dp) = sorted(dist.listdir(), key=lambda x: '.doc.zip' in x.basename)
        hub = devpi("upload", p, dp)
        url = hub.current.get_index_url().url + path
        out = out_devpi("getjson", url)
        data = json.loads(out.stdout.str())
        vv = ViewLinkStore(url, data["result"])
        assert len(vv.get_links()) == 2
        links = dict((x.rel, x.basename.lower()) for x in vv.get_links())
        assert links["releasefile"] == "%s.zip" % name_version_str
        assert links["doczip"] == "%s.doc.zip" % name_version_str


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
