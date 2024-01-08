from _pytest.outcomes import Failed
from devpi_common.metadata import parse_requirement
from devpi_common.metadata import parse_version
from devpi.list_remove import get_versions_to_delete
from devpi.list_remove import confirm_delete
from devpi.list_remove import out_index
from devpi.list_remove import out_project
from devpi.list_remove import show_commands
from pathlib import Path
import pytest


def linkver(index, basename, d=None, rel="releasefile"):
    if d is None:
        d = {}
    links = d.setdefault("+links", [])
    href = href="/{index}/+f/{basename}".format(index=index, basename=basename)
    links.append(dict(href=href, rel=rel))
    return d


@pytest.mark.parametrize(["input", "output"], [
    (["pkg1", "pkg2"], ["*pkg1*", "*pkg2*"]),
])
def test_out_index(loghub, input, output):
    out_index(loghub, input)
    matcher = loghub._getmatcher()
    matcher.fnmatch_lines(output)


@pytest.mark.parametrize(["input", "output"], [
    ({"1.0": linkver("root/dev", "p1-1.0.tar.gz"),
      "1.1": linkver("root/dev", "p1-1.1.tar.gz")},
     ["*p1-1.1.tar.gz*", "*p1-1.0.tar.gz*"]),
    #({"1.0": {"+links": dict(
    #    rel="releasefile", href="root/dev/pkg/1.0/p1-1.0.tar.gz"),
    #          "+shadowing": [{"+files":
    #                {"p1-1.0.tar.gz": "root/prod/pkg/1.0/p1-1.0.tar.gz"}}]}},
    #["*dev*p1-1.0.tar.gz*", "*prod*p1-1.0.tar.gz"]),
])
def test_out_project(loghub, input, output, monkeypatch):
    from devpi import list_remove
    loghub.current.reconfigure(dict(
        simpleindex="/index",
        index="/root/dev/",
        login="/login/",
    ))
    loghub.args.status = False
    loghub.args.all = True
    loghub.args.failures = None
    loghub.args.toxresults = None
    monkeypatch.setattr(list_remove, "show_test_status", lambda *args: None)

    class reply:
        url = ""
        result = input

    out_project(loghub, reply, parse_requirement("p1"))
    matcher = loghub._getmatcher()
    matcher.fnmatch_lines(output)

    loghub.args.all = False
    out_project(loghub, reply, parse_requirement("p1"))
    matcher = loghub._getmatcher()
    matcher.fnmatch_lines(output[0])


def test_confirm_delete(loghub, monkeypatch):
    loghub.current.reconfigure(dict(
        pypisubmit="/post",
        simpleindex="/index",
        index="/root/dev/",
        login="/login",
    ))
    monkeypatch.setattr(loghub, "ask_confirm", lambda msg: True)

    class r:
        result={"1.0": linkver("root/dev", "x-1.0.tar.gz"),
                "1.1": linkver("root/dev", "x-1.1.tar.gz")}
        type = "projectconfig"

    req = parse_requirement("x>=1.1")
    ver_to_delete = get_versions_to_delete(loghub.current.get_index_url(), r, req)
    assert confirm_delete(loghub, ver_to_delete)
    m = loghub._getmatcher()
    m.fnmatch_lines("""
        *x-1.1.tar.gz*
    """)
    assert "1.0" not in req
    assert "1.1" in req


def test_showcommands(loghub):
    loghub.args.failures = True
    show_commands(loghub, {"failed": True, "commands": [
        {"failed": False, "command": "ok_command", "output": "ok_output"},
        {"failed": True, "command": "fail_command", "output": "fail_output"},
    ]})
    loghub._getmatcher().fnmatch_lines("""
        *OK:*ok_command*
        *FAIL:*fail_command
        *fail_output*
    """)


class TestListRemove:
    def test_all(self, initproj, devpi, out_devpi):
        initproj("hello-1.0", {"doc": {
            "conf.py": "",
            "index.html": "<html/>"}})
        assert Path("setup.py").is_file()
        devpi("upload", "--no-isolation", "--formats", "sdist.zip")
        devpi("upload", "--no-isolation", "--formats", "sdist.zip,bdist_dumb")
        initproj("hello-1.1", {"doc": {
            "conf.py": "",
            "index.html": "<html/>"}})
        devpi("upload", "--no-isolation", "--formats", "sdist.zip")
        out = out_devpi("list", "hello")
        out.stdout.re_match_lines_random(r"""
            .*/hello-1\.1\.(tar\.gz|zip)
            .*/hello-1\.0\..+\.(tar\.gz|whl|zip)
            .*/hello-1\.0\.(tar\.gz|zip)""")
        assert len([x for x in out.stdout.lines if x.strip()]) == 3
        out = out_devpi("remove", "-y", "hello==1.0", code=200)
        out.stdout.fnmatch_lines_random("deleting release 1.0 of hello")
        out = out_devpi("list", "hello")
        out.stdout.re_match_lines_random(r"""
            .*/hello-1\.1\.(tar\.gz|zip)""")
        assert len([x for x in out.stdout.lines if x.strip()]) == 1
        out = out_devpi("remove", "-y", "hello==1.1", code=200)
        out.stdout.fnmatch_lines_random("deleting release 1.1 of hello")
        out = out_devpi("list")
        assert len([x for x in out.stdout.lines if x.strip()]) == 0
        out = out_devpi("list", "-v")
        assert len([x for x in out.stdout.lines if x.strip()]) == 0

    def test_remove_file(self, initproj, devpi, out_devpi, server_version, url_of_liveserver):
        if server_version < parse_version("4.6.0"):
            pytest.skip(
                "devpi-server before 4.6.0 didn't support deleting "
                "single release files.")
        initproj("hello-1.0", {"doc": {
            "conf.py": "",
            "index.html": "<html/>"}})
        assert Path("setup.py").is_file()
        devpi("upload", "--no-isolation", "--formats", "sdist.zip")
        devpi("upload", "--no-isolation", "--formats", "sdist.zip,bdist_dumb")
        initproj("hello-1.1", {"doc": {
            "conf.py": "",
            "index.html": "<html/>"}})
        devpi("upload", "--no-isolation", "--formats", "sdist.zip")
        out = out_devpi("list", "hello")
        out.stdout.re_match_lines_random(r"""
            .*/hello-1\.1\.(tar\.gz|zip)
            .*/hello-1\.0\..+\.(tar\.gz|whl|zip)
            .*/hello-1\.0\.(tar\.gz|zip)""")
        url = out.stdout.lines[0]
        out = out_devpi("remove", "-y", url, code=200)
        out.stdout.fnmatch_lines_random("""
           *About to remove the following file:
           """ + url)
        out = out_devpi("list", "hello")
        assert url not in out.stdout.str()

    @pytest.mark.parametrize("other_index", ["root/pypi", "/"])
    def test_all_index_option(self, initproj, devpi, out_devpi, other_index):
        import re
        initproj("hello-1.0", {"doc": {
            "conf.py": "",
            "index.html": "<html/>"}})
        assert Path("setup.py").is_file()
        devpi("upload", "--no-isolation", "--formats", "sdist.zip")
        devpi("upload", "--no-isolation", "--formats", "sdist.zip,bdist_dumb")
        initproj("hello-1.1", {"doc": {
            "conf.py": "",
            "index.html": "<html/>"}})
        devpi("upload", "--no-isolation", "--formats", "sdist.zip")

        # remember username
        out = out_devpi("use")
        user = re.search(r'\(logged in as (.+?)\)', out.stdout.str()).group(1)

        # go to other index
        devpi("use", other_index)
        out = out_devpi("list", "--index", "%s/dev" % user, "hello")
        out.stdout.re_match_lines_random(r"""
            .*/hello-1\.1\.(tar\.gz|zip)
            .*/hello-1\.0\..+\.(tar\.gz|whl|zip)
            .*/hello-1\.0\.(tar\.gz|zip)""")
        assert len([x for x in out.stdout.lines if x.strip()]) == 3
        out = out_devpi("remove", "--index", "%s/dev" % user, "-y", "hello==1.0", code=200)
        out.stdout.fnmatch_lines_random("deleting release 1.0 of hello")
        out = out_devpi("list", "--index", "%s/dev" % user, "hello")
        out.stdout.re_match_lines_random(r"""
            .*/hello-1\.1\.(tar\.gz|zip)""")
        assert len([x for x in out.stdout.lines if x.strip()]) == 1
        out = out_devpi("remove", "--index", "%s/dev" % user, "-y", "hello==1.1", code=200)
        out.stdout.fnmatch_lines_random("deleting release 1.1 of hello")
        out = out_devpi("list", "--index", "%s/dev" % user)
        assert len([x for x in out.stdout.lines if x.strip()]) == 0
        out = out_devpi("list", "--index", "%s/dev" % user, "-v")
        assert len([x for x in out.stdout.lines if x.strip()]) == 0

    def test_delete_version_with_inheritance(self, initproj, devpi, out_devpi):
        api = devpi("index", "-c", "dev2", "volatile=false")
        initproj("dddttt-0.2", {"doc": {
            "conf.py": "",
            "index.html": "<html/>"}})
        devpi("upload", "--index", "dev2", "--no-isolation", "--formats", "sdist.zip")
        devpi("index", "bases=%s/dev2" % api.current.username, "mirror_whitelist=*")
        initproj("dddttt-0.666", {"doc": {
            "conf.py": "",
            "index.html": "<html/>"}})
        assert Path("setup.py").is_file()
        devpi("upload", "--no-isolation", "--formats", "sdist.zip")
        out = out_devpi("list", "dddttt", "--all")
        out.stdout.re_match_lines_random(r".*/dev/.*/dddttt-0\.666\.(tar\.gz|zip)")
        out = out_devpi("remove", "dddttt==0.666", code=200)
        out = out_devpi("list", "dddttt", "--all")
        with pytest.raises((Failed, ValueError)):
            out.stdout.re_match_lines_random(r".*/dev/.*/dddttt-0\.666\.(tar\.gz|zip)")

    def test_delete_version_range_with_inheritance(self, initproj, devpi, out_devpi):
        import re
        # upload 0.666 to dev index
        initproj("dddttt-0.666", {"doc": {
            "conf.py": "",
            "index.html": "<html/>"}})
        assert Path("setup.py").is_file()
        devpi("upload", "--no-isolation", "--formats", "sdist.zip")
        # remember username
        out = out_devpi("use")
        user = re.search(r'\(logged in as (.+?)\)', out.stdout.str()).group(1)
        devpi("index", "-c", "dev2", "bases=%s/dev" % user)
        devpi("use", "dev2")
        # upload 1.0 to dev2 index
        initproj("dddttt-1.0", {"doc": {
            "conf.py": "",
            "index.html": "<html/>"}})
        assert Path("setup.py").is_file()
        devpi("upload", "--no-isolation", "--formats", "sdist.zip")
        # upload 2.0 to dev2 index
        initproj("dddttt-2.0", {"doc": {
            "conf.py": "",
            "index.html": "<html/>"}})
        assert Path("setup.py").is_file()
        devpi("upload", "--no-isolation", "--formats", "sdist.zip")

        out = out_devpi("list", "dddttt", "--all")
        out.stdout.re_match_lines_random(r".*/dev/.*/dddttt-0\.666\.(tar\.gz|zip)")
        out.stdout.re_match_lines_random(r".*/dev2/.*/dddttt-1\.0\.(tar\.gz|zip)")
        out.stdout.re_match_lines_random(r".*/dev2/.*/dddttt-2\.0\.(tar\.gz|zip)")
        out = out_devpi("remove", "dddttt<2.0", code=200)
        out = out_devpi("list", "dddttt", "--all")
        out.stdout.re_match_lines_random(r".*/dev/.*/dddttt-0\.666\.(tar\.gz|zip)")
        with pytest.raises((Failed, ValueError)):
            out.stdout.re_match_lines_random(r".*/dev/.*/dddttt-1\.0\.(tar\.gz|zip)")
        out.stdout.re_match_lines_random(r".*/dev2/.*/dddttt-2\.0\.(tar\.gz|zip)")

    def test_delete_project_with_inheritance(self, initproj, devpi, out_devpi, simpypi):
        api = devpi("index", "-c", "dev2", "volatile=false")
        initproj("dddttt-0.2", {"doc": {
            "conf.py": "",
            "index.html": "<html/>"}})
        devpi("upload", "--index", "dev2", "--no-isolation", "--formats", "sdist.zip")
        devpi("index", "bases=%s/dev2" % api.current.username, "mirror_whitelist=*")
        initproj("dddttt-0.666", {"doc": {
            "conf.py": "",
            "index.html": "<html/>"}})
        assert Path("setup.py").is_file()
        devpi("upload", "--no-isolation", "--formats", "sdist.zip")
        out = out_devpi("list", "dddttt", "--all")
        out.stdout.re_match_lines_random(r".*/dev/.*/dddttt-0\.666\.(tar\.gz|zip)")
        out = out_devpi("remove", "dddttt", code=200)
        out = out_devpi("list", "dddttt", "--all")
        with pytest.raises((Failed, ValueError)):
            out.stdout.re_match_lines_random(r".*/dev/.*/dddttt-0\.666\.(tar\.gz|zip)")

    def test_delete_file_non_volatile(self, initproj, devpi, out_devpi, server_version):
        if server_version < parse_version("6dev"):
            pytest.skip(
                "devpi-server before 6.0.0 didn't support deleting "
                "from non-volatile indexes.")
        devpi("index", "volatile=false")
        initproj("dddttt-0.666", {"doc": {
            "conf.py": "",
            "index.html": "<html/>"}})
        assert Path("setup.py").is_file()
        devpi("upload", "--no-isolation", "--formats", "sdist.zip")
        out = out_devpi("list", "dddttt", "--all")
        out.stdout.re_match_lines_random(r".*/dev/.*/dddttt-0\.666\.(tar\.gz|zip)")
        url = out.stdout.lines[0]
        out = out_devpi("remove", url, code=403)
        out = out_devpi("remove", "-f", url)
        out = out_devpi("list", "dddttt", "--all")
        with pytest.raises((Failed, ValueError)):
            out.stdout.re_match_lines_random(r".*/dev/.*/dddttt-0\.666\.(tar\.gz|zip)")

    def test_delete_project_non_volatile(self, initproj, devpi, out_devpi, server_version):
        if server_version < parse_version("6dev"):
            pytest.skip(
                "devpi-server before 6.0.0 didn't support deleting "
                "from non-volatile indexes.")
        devpi("index", "volatile=false")
        initproj("dddttt-0.666", {"doc": {
            "conf.py": "",
            "index.html": "<html/>"}})
        assert Path("setup.py").is_file()
        devpi("upload", "--no-isolation", "--formats", "sdist.zip")
        out = out_devpi("list", "dddttt", "--all")
        out.stdout.re_match_lines_random(r".*/dev/.*/dddttt-0\.666\.(tar\.gz|zip)")
        out = out_devpi("remove", "dddttt", code=403)
        out = out_devpi("remove", "--force", "dddttt")
        out = out_devpi("list", "dddttt", "--all")
        with pytest.raises((Failed, ValueError)):
            out.stdout.re_match_lines_random(r".*/dev/.*/dddttt-0\.666\.(tar\.gz|zip)")
