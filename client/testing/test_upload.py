import json
import os
import stat
import pytest
import re
import shutil
import sys
import tarfile
from devpi.upload import Checkout
from devpi.upload import find_parent_subpath
from devpi.upload import filter_latest
from devpi.upload import get_pkginfo
from devpi.upload import main
from devpi.upload import read_setupcfg
from devpi_common.contextlib import chdir
from io import BytesIO
from pathlib import Path
from textwrap import dedent
from devpi_common.metadata import splitbasename
from devpi_common.viewhelp import ViewLinkStore
from subprocess import check_output


@pytest.fixture
def datadir():
    return Path(__file__).parent / "data"


def runproc(cmd):
    args = cmd.split()
    path0 = args[0]
    if not os.path.isabs(path0):
        path0 = shutil.which(path0)
        if not path0:
            pytest.skip("%r not found" % args[0])
    return check_output([str(path0)] + args[1:])


@pytest.fixture
def uploadhub(request, tmpdir):
    from devpi.main import initmain
    hub, method = initmain([
        "devpitest",
        "--clientdir", tmpdir.join("client").strpath,
        "upload"])
    return hub


@pytest.mark.skipif("config.option.fast")
class TestCheckout:
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
        unicode_fn = str(unicode_fn, "utf8")
        setupdir.ensure(unicode_fn)
        if request.param == "hg":
            if not shutil.which("hg"):
                pytest.skip("'hg' command not found")
            with chdir(repo):
                runproc("hg init")
                runproc("hg add {0}/file {0}/link {0}/setup.py".format(setupdir_rel))
                runproc("hg add {0}/file {0}/{1}".format(setupdir_rel,
                                                         unicode_fn))
                runproc("hg commit --config ui.username=whatever -m message")
            return repo
        if not shutil.which("git"):
            pytest.skip("'git' command not found")
        with chdir(repo):
            runproc("git init")
            runproc("git config user.email 'you@example.com'")
            runproc("git config user.name 'you'")
            runproc("git add {0}/file {0}/link {0}/setup.py".format(setupdir_rel))
            runproc("git add {0}/file {0}/{1}".format(setupdir_rel,
                                                      unicode_fn))
            runproc("git commit -m message")
        return repo

    def test_vcs_export(self, uploadhub, repo, setupdir, tmpdir):
        checkout = Checkout(uploadhub, uploadhub.args, setupdir)
        assert checkout.rootpath == repo
        newrepo = Path(tmpdir.mkdir("newrepo").strpath)
        result = checkout.export(newrepo)
        assert result.rootpath.joinpath("file").exists()
        assert result.rootpath.joinpath("link").exists()
        if not sys.platform.startswith("win"):
            assert os.readlink(result.rootpath / "link") == ".."
        assert result.rootpath == newrepo / repo.basename / repo.bestrelpath(setupdir)
        # ensure we also copied repo meta info
        if repo.join(".hg").exists():
            assert list(newrepo.joinpath(repo.basename, ".hg").iterdir())
        else:
            assert list(newrepo.joinpath(repo.basename, ".git").iterdir())
        with uploadhub.workdir() as uploadbase:
            checkout.export(uploadbase)
            readonly = uploadbase / "readonly"
            readonly.write_text("foo")
            ro_bits = stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH
            os.chmod(str(readonly), ro_bits)
        assert not readonly.exists()
        assert not uploadbase.exists()

    def test_vcs_export_setupdironly(self, uploadhub, setupdir, tmpdir, monkeypatch):
        monkeypatch.setattr(uploadhub.args, "setupdironly", True)
        checkout = Checkout(uploadhub, uploadhub.args, setupdir)
        assert checkout.rootpath == setupdir
        newrepo = Path(tmpdir.mkdir("newrepo").strpath)
        result = checkout.export(newrepo)
        assert result.rootpath.joinpath("file").exists()
        assert result.rootpath.joinpath("link").exists()
        p = result.rootpath / "setup.py"
        assert p.exists()
        if not sys.platform.startswith("win"):
            assert p.stat().st_mode & int("0777", 8) == int("0777", 8)
            assert os.readlink(result.rootpath / "link") == '..'
        assert result.rootpath == newrepo / setupdir.basename

    def test_vcs_export_disabled(self, uploadhub, setupdir, tmpdir, monkeypatch):
        monkeypatch.setattr(uploadhub.args, "novcs", True)
        checkout = Checkout(uploadhub, uploadhub.args, setupdir)
        assert not checkout.hasvcs
        exported = checkout.export(Path(tmpdir.strpath))
        assert exported.rootpath == checkout.setupdir

    def test_vcs_export_verify_setup(self, uploadhub, setupdir, tmpdir):
        subdir = setupdir.mkdir("subdir")
        subdir.ensure("setup.py")
        checkout = Checkout(uploadhub, uploadhub.args, subdir)
        wc = Path(tmpdir.mkdir("wc").strpath)
        exported = checkout.export(wc)
        assert not exported.rootpath.joinpath("setup.py").exists()

    def test_export_attributes(self, uploadhub, setupdir, tmpdir):
        checkout = Checkout(uploadhub, uploadhub.args, setupdir)
        setupdir.join("setup.py").write(dedent("""
            from setuptools import setup
            # some packages like numpy produce output during build, simulate:
            print("* foo, bar")
            setup(name="xyz", version="1.2.3")
        """))
        exported = checkout.export(Path(tmpdir.strpath))
        name, version = exported.setup_name_and_version()
        assert name == "xyz"
        assert version == "1.2.3"

    def test_setup_build_docs(self, uploadhub, setupdir, tmpdir):
        checkout = Checkout(uploadhub, uploadhub.args, setupdir)
        setupdir.join("setup.py").write(dedent("""
            from setuptools import setup
            setup(name="xyz", version="1.2.3")
        """))
        exported = checkout.export(Path(tmpdir.strpath))
        assert exported.rootpath != exported.origrepo
        # we have to mock a bit unfortunately
        # to find out if the sphinx building popen command
        # is called with the exported directory instead of he original
        l = []
        old_popen_output = exported.hub.popen_output

        def mock_popen_output(args, **kwargs):
            if "sphinx-build" in args:
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
def test_post_includes_auth_info(initproj, uploadhub):
    class Session:
        posts = []

        def post(self, *args, **kwargs):
            class reply:
                status_code = 200
            self.posts.append((args, kwargs))
            return reply

    class args:
        dryrun = None
        sdist = False
        wheel = False
        formats = None
        index = None
        no_isolation = True
        novcs = None
        only_latest = None
        onlydocs = None
        path = None
        python = None
        setupdironly = None
        verbose = 0
        withdocs = None

    initproj("pkg-1.0")
    tmpdir = Path()
    certpath = str(tmpdir / "cert.key")
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
    (upload1, upload2) = Session.posts
    assert upload1[0][1][":action"] == "file_upload"
    assert upload1[1]["auth"] == ("basic", "auth")
    assert upload1[1]["cert"] == certpath
    assert "X-Devpi-Auth" in upload1[1]["headers"]
    assert upload2[0][1][":action"] == "file_upload"
    assert upload2[1]["auth"] == ("basic", "auth")
    assert upload2[1]["cert"] == certpath
    assert "X-Devpi-Auth" in upload2[1]["headers"]


@pytest.mark.skipif("config.option.fast")
def test_post_data(initproj, monkeypatch, reqmock, uploadhub):
    import email

    class args:
        dryrun = None
        sdist = False
        wheel = False
        formats = None
        index = None
        no_isolation = True
        novcs = None
        only_latest = None
        onlydocs = None
        path = None
        python = None
        setupdironly = None
        verbose = 0
        withdocs = None

    class Response:
        status_code = 200

    sent = []

    def send(req, **kw):
        sent.append((req, kw))
        return Response()

    initproj("pkg-1.0")
    uploadhub.cwd = Path()
    uploadhub.current.reconfigure(dict(
        index="http://devpi/foo/bar",
        login="http://devpi/+login",
        pypisubmit="http://devpi/foo/bar"))
    monkeypatch.setattr(uploadhub.http, "send", send)
    main(uploadhub, args)
    # convert POST data to Message
    msg = email.message_from_bytes(
        b"MIME-Version: 1.0\nContent-Type: %s\n\n%s" % (
            sent[0][0].headers['Content-Type'].encode('ascii'),
            sent[0][0].body))
    # get the data
    data = {
        x.get_param("name", header="Content-Disposition"): x.get_payload()
        for x in msg.get_payload()}
    assert data[":action"] == "file_upload"
    assert data["name"] == "pkg"
    assert data["protocol_version"] == "1"
    assert data["version"] == "1.0"


@pytest.mark.skipif("config.option.fast")
def test_post_derived_devpi_token(initproj, uploadhub):
    from base64 import b64decode
    import pypitoken

    class Session:
        posts = []

        def post(self, *args, **kwargs):
            class reply:
                status_code = 200
            self.posts.append((args, kwargs))
            return reply

    class args:
        dryrun = None
        formats = None
        index = None
        no_isolation = True
        novcs = None
        only_latest = None
        onlydocs = None
        path = None
        python = None
        sdist = False
        setupdironly = None
        withdocs = None
        verbose = 0
        wheel = True

    initproj("pkg-1.0")
    passwd = "devpi-AgEAAhFmc2NodWx6ZS1yTlk5a0RuYQAABiBcjsOFkn7_3fn6mFoeJve_cOv-thDRL-4fQzbf_sOGjQ"
    token = pypitoken.token.Token.load(passwd)
    assert pypitoken.ProjectNamesRestriction(
        project_names=["pkg"]) not in token.restrictions
    uploadhub.cwd = Path()
    uploadhub.http = Session()
    uploadhub.current.reconfigure(dict(
        index="http://devpi/foo/bar",
        login="http://devpi/+login",
        pypisubmit="http://devpi/foo/bar"))
    uploadhub.current.set_auth("devpi", passwd)
    main(uploadhub, args)
    ((post_args, post_kwargs),) = Session.posts
    auth = post_kwargs['headers']['X-Devpi-Auth']
    (username, derived_passwd) = (
        x.decode('ascii') for x in b64decode(auth).split(b':'))
    assert username == 'devpi'
    assert derived_passwd != passwd
    derived_token = pypitoken.token.Token.load(derived_passwd)
    assert pypitoken.ProjectNamesRestriction(
        project_names=["pkg"]) in derived_token.restrictions


class TestUploadFunctional:
    @pytest.fixture(params=["hello-1.0", "my-pkg-123-1.0"])
    def projname_version_project(self, request, initproj):
        project = initproj(request.param.rsplit("-", 1), {
            "doc" if request.param.startswith("hello") else "docs":
            {
                "conf.py": "#nothing",
                "contents.rst": "",
                "index.html": "<html/>"}})
        return (request.param, project)

    @pytest.fixture
    def projname_version(self, projname_version_project):
        return projname_version_project[0]

    def test_plain_dry_run(self, devpi, out_devpi, projname_version):
        assert Path("setup.py").is_file()
        out = out_devpi("upload", "--no-isolation", "--dry-run")
        assert out.ret == 0
        out.stdout.fnmatch_lines("""
            built:*
            skipped: file_upload of {projname_version}.*
            """.format(projname_version=projname_version))

    def test_with_docs_dry_run(self, devpi, out_devpi, projname_version):
        out = out_devpi("upload", "--no-isolation", "--dry-run", "--with-docs")
        assert out.ret == 0
        out.stdout.fnmatch_lines("""
            built:*
            skipped: file_upload of {projname_version}.*
            skipped: doc_upload of {projname_version}.doc.zip*
            """.format(projname_version=projname_version))

    def test_only_docs_dry_run(self, devpi, out_devpi, projname_version):
        out = out_devpi("upload", "--no-isolation", "--dry-run", "--only-docs")
        assert out.ret == 0
        out.stdout.fnmatch_lines("""
            built:*
            skipped: doc_upload of {projname_version}.doc.zip*
            """.format(projname_version=projname_version))

    @pytest.mark.parametrize("path", [
        "foo.doc.zip",
        "foo.docs.zip"])
    def test_only_docs_with_path_no_version(self, devpi, out_devpi, path, tmpdir):
        archive_path = tmpdir.join(path)
        archive_path.ensure()
        tmpdir.chdir()
        out = out_devpi("upload", "--no-isolation", "--only-docs", path)
        assert out.ret == 1
        out.stdout.fnmatch_lines(
            "doczip has no version and 'foo' has no releases to derive one from")

    @pytest.mark.parametrize("path", [
        "foo.doc.tar.gz",
        "foo.docs.tgz"])
    def test_only_docs_with_path_no_version_gz(self, devpi, out_devpi, path, tmpdir):
        archive_path = tmpdir.join(path)
        with tarfile.TarFile(archive_path.strpath, "w") as tgz:
            tgz.addfile(tarfile.TarInfo("index.html"), BytesIO(b""))
        tmpdir.chdir()
        out = out_devpi("upload", "--no-isolation", "--only-docs", path)
        assert out.ret == 1
        out.stdout.fnmatch_lines("""
            repackaged {path} to foo.doc.zip
            doczip has no version and 'foo' has no releases to derive one from
            """.format(path=path))

    @pytest.mark.parametrize("path", [
        "foo-1.0.doc.zip",
        "foo-1.0.docs.zip"])
    def test_only_docs_with_path(self, devpi, out_devpi, path, tmpdir):
        archive_path = tmpdir.join(path)
        archive_path.ensure()
        tmpdir.chdir()
        out = out_devpi("upload", "--no-isolation", "--only-docs", path)
        assert out.ret == 0
        out.stdout.fnmatch_lines("""
            doc_upload of {path}*
            """.format(path=path))

    @pytest.mark.parametrize("path", [
        "foo-1.0.doc.tar.gz",
        "foo-1.0.docs.tgz"])
    def test_only_docs_with_path_gz(self, devpi, out_devpi, path, tmpdir):
        archive_path = tmpdir.join(path)
        with tarfile.TarFile(archive_path.strpath, "w") as tgz:
            tgz.addfile(tarfile.TarInfo("index.html"), BytesIO(b""))
        tmpdir.chdir()
        out = out_devpi("upload", "--no-isolation", "--only-docs", path)
        assert out.ret == 0
        out.stdout.fnmatch_lines("""
            repackaged {path} to foo-1.0.doc.zip
            doc_upload of foo-1.0.doc.zip*
            """.format(path=path))

    def test_plain_with_docs(self, devpi, out_devpi, projname_version):
        out = out_devpi("upload", "--no-isolation", "--with-docs", code=[200, 200, 200])
        assert out.ret == 0
        out.stdout.fnmatch_lines("""
            built:*
            file_upload of {projname_version}.*
            doc_upload of {projname_version}.doc.zip*
            """.format(projname_version=projname_version))

    def test_no_artifacts_in_docs(self, out_devpi, projname_version_project):
        from devpi_common.archive import Archive
        out = out_devpi("upload", "--wheel", "--with-docs", code=[200, 200])
        assert out.ret == 0
        (projname_version, project) = projname_version_project
        projname_version_norm = projname_version.replace("-", "*")
        out.stdout.fnmatch_lines("""
            built:*
            file_upload of {projname_version_norm}*.whl*
            doc_upload of {projname_version}.doc.zip*
            """.format(
            projname_version=projname_version,
            projname_version_norm=projname_version_norm))
        archive_path = project.join('dist', '%s.doc.zip' % projname_version)
        with Archive(archive_path) as archive:
            artifacts = [
                x for x in archive.namelist()
                if x.startswith(('lib/', 'bdist'))]
            assert artifacts == []

    def test_sdist_zip_with_docs(self, devpi, out_devpi, projname_version):
        out = out_devpi(
            "upload", "--formats", "sdist.zip", "--with-docs", code=[200, 200])
        assert out.ret == 0
        out.stdout.re_match_lines(r"""
            built:.*
            file_upload of {projname_version}\.(tar\.gz|zip)
            doc_upload of {projname_version}\.doc\.zip
            """.format(projname_version=projname_version))

    def test_sdist_zip(self, devpi, out_devpi, projname_version):
        out = out_devpi("upload", "--no-isolation", "--formats", "sdist.zip", code=[200])
        assert out.ret == 0
        out.stdout.re_match_lines(r"""
            built:
            file_upload of {projname_version}\.(tar\.gz|zip)
            """.format(projname_version=projname_version))

    def test_sdist(self, devpi, out_devpi, projname_version):
        out = out_devpi("upload", "--no-isolation", "--sdist", code=[200])
        assert out.ret == 0
        out.stdout.fnmatch_lines("""
            built:*
            file_upload of {projname_version}*
            """.format(projname_version=projname_version))

    def test_bdist_wheel(self, devpi, out_devpi, projname_version):
        out = out_devpi("upload", "--no-isolation", "--formats", "bdist_wheel", code=[200])
        assert out.ret == 0
        projname_version_norm = projname_version.replace("-", "*")
        out.stdout.fnmatch_lines("""
            The --formats option is deprecated, replace it with --wheel to only*
            built:*
            file_upload of {projname_version_norm}*.whl*
            """.format(projname_version_norm=projname_version_norm))

    def test_wheel_setup_cfg(self, devpi, initproj, out_devpi):
        initproj("pkg-1.0", kind="setup.cfg")
        out = out_devpi("upload", "--no-isolation", "--wheel", code=[200])
        assert out.ret == 0
        out.stdout.fnmatch_lines("""
            built:*
            file_upload of pkg-1.0-*.whl*
            """)

    def test_wheel_pyproject_toml(self, devpi, initproj, out_devpi):
        initproj("pkg-1.0", kind="pyproject.toml")
        out = out_devpi("upload", "--wheel", code=[200])
        assert out.ret == 0
        out.stdout.fnmatch_lines("""
            built:*
            file_upload of pkg-1.0-*.whl*
            """)

    def test_default_formats(self, devpi, out_devpi, projname_version):
        out = out_devpi(
            "upload", "--formats", "sdist,bdist_wheel", code=[200, 200])
        assert out.ret == 0
        projname_version_norm = projname_version.replace("-", ".")
        out.stdout.re_match_lines_random(r"""
            The --formats option is deprecated, you can remove it to get the
            built:
            file_upload of {projname_version_norm}-.+\.whl
            file_upload of {projname_version}\.(tar\.gz|zip)
            """.format(
            projname_version=projname_version,
            projname_version_norm=projname_version_norm))

    def test_deprecated_formats(self, devpi, out_devpi, projname_version):
        out = out_devpi(
            "upload", "--formats", "bdist_dumb,bdist_egg", code=[200, 200])
        assert out.ret == 0
        projname_version_norm = projname_version.replace("-", ".")
        out.stdout.re_match_lines_random(r"""
            The --formats option is deprecated, none of the specified formats 'bdist_dumb,bdist_egg'
            .*Falling back to 'setup\.py bdist_dumb' which
            .*Falling back to 'setup\.py bdist_egg' which
            built:
            file_upload of {projname_version}.*\.(tar\.gz|zip)
            file_upload of {projname_version_norm}.*\.egg
            """.format(
            projname_version=projname_version,
            projname_version_norm=projname_version_norm))

    def test_plain(self, devpi, out_devpi, projname_version):
        out = out_devpi("upload", "--no-isolation", code=[200, 200])
        out.stdout.fnmatch_lines_random("""
            file_upload of {projname_version}.*
            file_upload of {projname_version_norm}*.whl*
            """.format(projname_version=projname_version,
                       projname_version_norm=projname_version.replace("-", "*")
                       ))

    def test_upload_to_mirror(
            self, devpi, initproj, out_devpi, projname_version):
        initproj(projname_version.rsplit("-", 1), {"doc": {
            "conf.py": "#nothing",
            "contents.rst": "",
            "index.html": "<html/>"}})
        assert Path("setup.py").is_file()

        # use mirror
        out = out_devpi("use", "root/pypi")
        out.stdout.fnmatch_lines_random("current devpi index*/root/pypi*")
        out = out_devpi("upload", "--no-isolation", "--dry-run")
        out.stdout.fnmatch_lines_random("*does not support upload.")
        out.stdout.fnmatch_lines_random("*it is a mirror.")

    @pytest.mark.parametrize("other_index", ["root/pypi", "/"])
    def test_index_option(
            self, devpi, initproj, out_devpi, other_index, projname_version):
        initproj(projname_version.rsplit("-", 1), {"doc": {
            "conf.py": "#nothing",
            "contents.rst": "",
            "index.html": "<html/>"}})
        assert Path("setup.py").is_file()
        # remember username
        out = out_devpi("use")
        user = re.search(r'\(logged in as (.+?)\)', out.stdout.str()).group(1)

        # go to other index
        out = out_devpi("use", other_index)

        # --index option
        out = out_devpi("upload", "--no-isolation", "--index", "%s/dev" % user, "--dry-run")
        out.stdout.fnmatch_lines_random("skipped: file_upload*to*/%s/dev*" % user)

    @pytest.mark.parametrize("other_index", ["root/pypi", "/"])
    def test_index_option_with_environment_relative(
            self, devpi, initproj, monkeypatch, out_devpi,
            other_index, projname_version):
        initproj(projname_version.rsplit("-", 1), {"doc": {
            "conf.py": "#nothing",
            "contents.rst": "",
            "index.html": "<html/>"}})
        assert Path("setup.py").is_file()
        # remember username
        out = out_devpi("use")
        user = re.search(r'\(logged in as (.+?)\)', out.stdout.str()).group(1)

        # go to other index
        out = out_devpi("use", other_index)

        monkeypatch.setenv("DEVPI_INDEX", "user/dev")
        # --index option
        out = out_devpi("upload", "--no-isolation", "--index", "%s/dev" % user, "--dry-run")
        out.stdout.fnmatch_lines_random("skipped: file_upload*to*/%s/dev*" % user)

    def test_logout(self, capfd, devpi, out_devpi, projname_version):
        # logoff then upload
        out = out_devpi("logoff")
        out.stdout.fnmatch_lines_random("login information deleted")

        # see if we get an error return code
        (out, err) = capfd.readouterr()
        res = devpi("upload", "--no-isolation")
        (out, err) = capfd.readouterr()
        assert "401 FAIL file_upload" in out
        assert "Unauthorized" in out
        assert isinstance(res.sysex, SystemExit)
        assert res.sysex.args == (1,)

    def test_fromdir(self, initproj, devpi, out_devpi, runproc):
        initproj("hello-1.1", {"doc": {
            "conf.py": "",
            "index.html": "<html/>"}})
        tmpdir = Path()
        runproc(tmpdir, "python setup.py sdist --format=zip".split())
        initproj("hello-1.2")
        runproc(tmpdir, "python setup.py sdist --format=zip".split())
        dist = tmpdir / "dist"
        assert len(list(dist.iterdir())) == 2
        hub = devpi("upload", "--no-isolation", "--from-dir", dist)
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
        tmpdir = Path()
        runproc(tmpdir, "python setup.py sdist --format=zip".split())
        dist = tmpdir / "dist"
        zip_dir(tmpdir / 'doc', dist / f"{name_version_str}.doc.zip")
        assert len(list(dist.iterdir())) == 2
        (p, dp) = sorted(dist.iterdir(), key=lambda x: '.doc.zip' in x.name)
        hub = devpi("upload", "--no-isolation", p, dp)
        url = hub.current.get_index_url().url + path
        out = out_devpi("getjson", url)
        data = json.loads(out.stdout.str())
        vv = ViewLinkStore(url, data["result"])
        assert len(vv.get_links()) == 2
        links = dict((x.rel, x.basename.lower()) for x in vv.get_links())
        assert links["releasefile"] == "%s.zip" % name_version_str
        assert links["doczip"] == "%s.doc.zip" % name_version_str

    def test_cli_sdist_precedence(self, initproj, devpi, out_devpi):
        initproj("pkg-1.0")
        tmpdir = Path()
        tmpdir.joinpath("setup.cfg").write_text(dedent("""
            [devpi:upload]
            formats=bdist_wheel,sdist.zip"""))
        hub = devpi("upload", "--sdist", "--no-isolation")
        url = hub.current.get_index_url().url + 'pkg/1.0/'
        out = out_devpi("getjson", url)
        data = json.loads(out.stdout.str())
        vv = ViewLinkStore(url, data["result"])
        assert len(vv.get_links()) == 1
        assert vv.get_links()[0].basename in ('pkg-1.0.tar.gz', 'pkg-1.0.zip')

    def test_cli_wheel_precedence(self, initproj, devpi, out_devpi):
        initproj("pkg-1.0")
        tmpdir = Path()
        tmpdir.joinpath("setup.cfg").write_text(dedent("""
            [devpi:upload]
            formats=bdist_wheel,sdist.zip"""))
        hub = devpi("upload", "--wheel", "--no-isolation")
        url = hub.current.get_index_url().url + 'pkg/1.0/'
        out = out_devpi("getjson", url)
        data = json.loads(out.stdout.str())
        vv = ViewLinkStore(url, data["result"])
        assert len(vv.get_links()) == 1
        assert vv.get_links()[0].basename in (
            'pkg-1.0-py2-none-any.whl',
            'pkg-1.0-py3-none-any.whl')


def test_getpkginfo(datadir):
    info = get_pkginfo(datadir / "dddttt-0.1.dev45-py27-none-any.whl")
    assert info.name == "dddttt"
    assert info.metadata_version == "2.0"
    info = get_pkginfo(datadir / "ddd-1.0.doc.zip")
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


@pytest.mark.parametrize("structure", [
    {"doc": {"conf.py": "", "index.rst": "", "contents.rst": ""}},
    {"docs": {"conf.py": "", "index.rst": "", "contents.rst": ""}},
    {"doc": {"source": {"conf.py": "", "index.rst": "", "contents.rst": ""}}},
    {"docs": {"source": {"conf.py": "", "index.rst": "", "contents.rst": ""}}},
    {"source": {"conf.py": "", "index.rst": "", "contents.rst": ""}},
])
def test_build_docs(initproj, out_devpi, structure):
    proj = initproj("hello1.1", structure)
    out = out_devpi("upload", "--no-isolation", "--dry-run", "--only-docs")
    assert out.ret == 0

    docs = proj.join("dist/hello1.1-0.1.doc.zip")
    assert docs.isfile()
