import subprocess
import pytest
import tox
from devpi.test import *

pytest_plugins = "pytester"

def test_post_tox_json_report(loghub, mock_http_api):
    mock_http_api.set("http://devpi.net", 200, result={})
    post_tox_json_report(loghub, "http://devpi.net", {"hello": "123"})
    assert len(mock_http_api.called) == 1
    loghub._getmatcher().fnmatch_lines("""
        *posting*
        *success*
    """)

def test_post_tox_json_report_error(loghub, mock_http_api):
    mock_http_api.set("http://devpi.net/+tests", 404)
    post_tox_json_report(loghub, "http://devpi.net/+tests", {"hello": "123"})
    assert len(mock_http_api.called) == 1
    loghub._getmatcher().fnmatch_lines("""
        *could not post*http://devpi.net/+tests*
    """)

@pytest.fixture
def pseudo_current():
    class Current:
        simpleindex = "http://pseudo/user/index/"
    return Current

def contains_sublist(list1, sublist):
    len_sublist = len(sublist)
    assert len_sublist <= len(list1)
    for i in range(len(list1)):
        if list1[i:i+len_sublist] == sublist:
            return True
    return False

def test_passthrough_args_toxargs(makehub, tmpdir, pseudo_current):
    hub = makehub(["test", "--tox-args", "-- -x", "somepkg"])
    index = DevIndex(hub, tmpdir, pseudo_current)
    tmpdir.ensure("tox.ini")
    args = index.get_tox_args(unpack_path=tmpdir)
    assert args[-2:] == ["--", "-x"]


def test_index_option(create_and_upload, devpi, monkeypatch, out_devpi):
    import re

    def runtox(self, *args, **kwargs):
        self.hub.info("Mocked tests ... %r %r" % (args, kwargs))
    monkeypatch.setattr("devpi.test.DevIndex.runtox", runtox)

    create_and_upload("exa-1.0")

    # remember username
    out = out_devpi("use")
    (url, user) = re.search(
        '(https?://.+?)\s+\(logged in as (.+?)\)', out.stdout.str()).groups()

    # go to other index
    devpi("use", "root/pypi")

    out = out_devpi("test", "--index", "%s/dev" % user, "exa")
    out.stdout.fnmatch_lines("""
        received*/%s/dev/*exa-1.0*
        unpacking*
        Mocked tests ...*""" % user)

    # forget current server index
    devpi("use", "--delete")

    out = out_devpi("test", "--index", url, "exa")
    out.stdout.fnmatch_lines("""
        received*/%s/dev/*exa-1.0*
        unpacking*
        Mocked tests ...*""" % user)


def test_toxini(makehub, tmpdir, pseudo_current):
    toxini = tmpdir.ensure("new-tox.ini")
    hub = makehub(["test", "-c", toxini, "somepkg"])
    index = DevIndex(hub, tmpdir, pseudo_current)
    tmpdir.ensure("tox.ini")
    args = index.get_tox_args(unpack_path=tmpdir)
    assert contains_sublist(args, ["-c", str(toxini)])

def test_passthrough_args_env(makehub, tmpdir, pseudo_current):
    hub = makehub(["test", "-epy27", "somepkg"])
    index = DevIndex(hub, tmpdir, pseudo_current)
    tmpdir.ensure("tox.ini")
    args = index.get_tox_args(unpack_path=tmpdir)
    assert contains_sublist(args, ["-epy27"])

def test_no_detox(makehub, tmpdir, pseudo_current):
    hub = makehub(["test", "-epy27", "somepkg"])
    index = DevIndex(hub, tmpdir, pseudo_current)
    runner = index.get_tox_runner()
    assert runner == tox.cmdline

def test_detox(makehub, tmpdir, pseudo_current):
    detox_main = pytest.importorskip("detox.main")
    hub = makehub(["test", "--detox", "-epy27", "somepkg"])
    index = DevIndex(hub, tmpdir, pseudo_current)
    runner = index.get_tox_runner()
    assert runner == detox_main.main


def test_fallback_ini(makehub, tmpdir, pseudo_current):
    p = tmpdir.ensure("mytox.ini")
    hub = makehub(["test", "--fallback-ini", str(p), "somepkg"])
    index = DevIndex(hub, tmpdir, pseudo_current)
    args = index.get_tox_args(unpack_path=tmpdir)
    assert contains_sublist(args, ["-c", str(p)])
    p2 = tmpdir.ensure("tox.ini")
    args = index.get_tox_args(unpack_path=tmpdir)
    assert contains_sublist(args, ["-c", str(p2)])

class TestWheel:
    def test_find_wheels_and_sdist(self, loghub):
        vl = ViewLinkStore("http://something/index", {"+links": [
            {"href": "http://b/pytest-2.7.0.zip", "rel": "releasefile"},
            {"href": "http://b/pytest-2.7.0.tar.gz", "rel": "releasefile"},
            {"href": "http://b/pytest-2.7.0-py2.py3-none-any.whl", "rel": "releasefile"},
        ]})
        links = vl.get_links(rel="releasefile")
        sdist_links, wheel_links = find_sdist_and_wheels(loghub, links)
        assert len(sdist_links) == 2
        assert sdist_links[0].basename.endswith(".tar.gz")
        assert sdist_links[1].basename.endswith(".zip")
        assert len(wheel_links) == 1
        assert wheel_links[0].basename == "pytest-2.7.0-py2.py3-none-any.whl"

    def test_find_wheels_and_no_sdist(self, loghub):
        vl = ViewLinkStore("http://something/index", {"+links": [
            {"href": "http://b/pytest-2.7.0-py2.py3-none-any.whl", "rel": "releasefile"},
        ]})
        links = vl.get_links(rel="releasefile")
        with pytest.raises(SystemExit):
            find_sdist_and_wheels(loghub, links)

        loghub._getmatcher().fnmatch_lines("""
            *need at least one sdist*
        """)

    def test_find_wheels_not_universal(self, loghub):
        vl = ViewLinkStore("http://something/index", {"+links": [
            {"href": "http://b/pytest-2.7.0-py26-none-any.whl", "rel": "releasefile"},
        ]})
        links = vl.get_links(rel="releasefile")
        with pytest.raises(SystemExit):
            find_sdist_and_wheels(loghub, links)

        loghub._getmatcher().fnmatch_lines("""
            *only universal wheels*
        """)

    @pytest.mark.skipif("sys.version_info < (2,7)")
    def test_prepare_toxrun_args(self, loghub, pseudo_current, tmpdir, reqmock, initproj):
        # XXX this test was a bit hard to setup and is also somewhat covered by
        # the below wheel functional test so unclear if it's worth to
        # maintain it (but now that we have it ...)
        vl = ViewLinkStore("http://something/index", {"+links": [
            {"href": "http://b/prep1-1.0.zip", "rel": "releasefile"},
            {"href": "http://b/prep1-1.0.tar.gz", "rel": "releasefile"},
            {"href": "http://b/prep1-1.0-py2.py3-none-any.whl", "rel": "releasefile"},
        ], "name": "prep1", "version": "1.0"})
        links = vl.get_links(rel="releasefile")
        sdist_links, wheel_links = find_sdist_and_wheels(loghub, links)
        dev_index = DevIndex(loghub, tmpdir, pseudo_current)

        initproj("prep1-1.0", filedefs={})
        subprocess.check_call(["python", "setup.py", "sdist", "--formats=gztar,zip"])
        subprocess.check_call(["python", "setup.py", "bdist_wheel", "--universal"])
        for p in py.path.local("dist").listdir():
            reqmock.mockresponse("http://b/" + p.basename, code=200, method="GET",
                                 data=p.read("rb"))
        toxrunargs = prepare_toxrun_args(dev_index, vl, sdist_links, wheel_links)
        assert len(toxrunargs) == 3
        sdist1, sdist2, wheel1 = toxrunargs
        assert sdist1[0].basename == "prep1-1.0.tar.gz"
        assert sdist1[1].path_unpacked.strpath.endswith("targz" + os.sep + "prep1-1.0")
        assert sdist2[0].basename == "prep1-1.0.zip"
        assert sdist2[1].path_unpacked.strpath.endswith("zip" + os.sep + "prep1-1.0")
        assert wheel1[0].basename == "prep1-1.0-py2.py3-none-any.whl"
        assert str(wheel1[1].path_unpacked).endswith(wheel1[0].basename)

    def test_wheels_and_sdist(self, out_devpi, create_and_upload):
        create_and_upload("exa-1.0", filedefs={
           "tox.ini": """
              [testenv]
              commands = python -c "print('ok')"
            """,
            "setup.cfg": """
                [bdist_wheel]
                universal = True
            """
        }, opts=["--format=sdist.zip,bdist_wheel"])
        result = out_devpi("test", "-epy", "--debug", "exa==1.0")
        assert result.ret == 0
        result.stdout.fnmatch_lines("""*exa-1.0.*""")
        result = out_devpi("list", "-f", "exa")
        assert result.ret == 0
        result.stdout.fnmatch_lines_random("""
            *exa-1.0*whl*
            *tests*passed*
            *exa-1.0*zip*
            *tests*passed*
        """)


class TestFunctional:
    @pytest.mark.xfail(reason="output capturing for devpi calls")
    def test_main_nopackage(self, out_devpi):
        result = out_devpi("test", "--debug", "notexists73", ret=1)
        result.fnmatch_lines([
            "*could not find/receive*",
        ])

    def test_main_example(self, out_devpi, create_and_upload):
        create_and_upload("exa-1.0", filedefs={
           "tox.ini": """
              [testenv]
              commands = python -c "print('ok')"
            """,
        })
        result = out_devpi("test", "--debug", "exa")
        assert result.ret == 0
        result = out_devpi("list", "-f", "exa")
        assert result.ret == 0
        result.stdout.fnmatch_lines("""*tests passed*""")

    def test_no_post(self, out_devpi, create_and_upload, monkeypatch):
        def post(*args, **kwargs):
            0 / 0

        create_and_upload("exa-1.0", filedefs={
            "tox.ini": """
              [testenv]
              commands = python -c "print('ok')"
            """})
        monkeypatch.setattr("devpi.test.post_tox_json_report", post)
        result = out_devpi("test", "--no-upload", "exa")
        assert result.ret == 0

    def test_specific_version(self, out_devpi, create_and_upload):
        create_and_upload("exa-1.0", filedefs={
           "tox.ini": """
              [testenv]
              commands = python -c "print('ok')"
            """,
        })
        create_and_upload("exa-1.1", filedefs={
           "tox.ini": """
              [testenv]
              commands = python -c "print('ok')"
            """,
        })
        result = out_devpi("test", "--debug", "exa==1.0")
        assert result.ret == 0
        result.stdout.fnmatch_lines("""*exa-1.0.*""")
        result = out_devpi("list", "-f", "exa")
        assert result.ret == 0
        result.stdout.fnmatch_lines("""
            *exa-1.1.*
            *exa-1.0.*
            *tests passed*""")

    def test_pkgname_with_dashes(self, out_devpi, create_and_upload):
        create_and_upload(("my-pkg-123", "1.0"), filedefs={
           "tox.ini": """
              [testenv]
              commands = python -c "print('ok')"
            """,
        })
        result = out_devpi("test", "--debug", "my-pkg-123")
        assert result.ret == 0
        result = out_devpi("list", "-f", "my-pkg-123")
        assert result.ret == 0
        result.stdout.fnmatch_lines("""*tests passed*""")
