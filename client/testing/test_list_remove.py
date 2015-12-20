import py
import pytest
from devpi.list_remove import *
from devpi import list_remove


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
     ["*p1-1.1.tar.gz*", "*p1-1.0.tar.gz*", ]),
    #({"1.0": {"+links": dict(
    #    rel="releasefile", href="root/dev/pkg/1.0/p1-1.0.tar.gz"),
    #          "+shadowing": [{"+files":
    #                {"p1-1.0.tar.gz": "root/prod/pkg/1.0/p1-1.0.tar.gz"}}]}},
    #["*dev*p1-1.0.tar.gz*", "*prod*p1-1.0.tar.gz"]),
])
def test_out_project(loghub, input, output, monkeypatch):
    loghub.current.reconfigure(dict(
                simpleindex="/index",
                index="/root/dev/",
                login="/login/",
                ))
    loghub.args.status = False
    loghub.args.all = True
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
    assert confirm_delete(loghub, loghub.current.get_index_url(), r, req)
    m = loghub._getmatcher()
    m.fnmatch_lines("""
        *x-1.1.tar.gz*
    """)
    assert "x-1.0" not in req


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
        assert py.path.local("setup.py").check()
        devpi("upload", "--formats", "sdist.zip")
        devpi("upload", "--formats", "sdist.zip,bdist_dumb")
        initproj("hello-1.1", {"doc": {
            "conf.py": "",
            "index.html": "<html/>"}})
        devpi("upload", "--formats", "sdist.zip")
        out = out_devpi("list", "hello")
        out.stdout.fnmatch_lines_random("""
            */hello-1.1.zip
            */hello-1.0*
            */hello-1.0.zip""")
        assert len([x for x in out.stdout.lines if x.strip()]) == 3
        out = out_devpi("remove", "-y", "hello==1.0", code=200)
        out.stdout.fnmatch_lines_random("deleting release 1.0 of hello")
        out = out_devpi("list", "hello")
        out.stdout.fnmatch_lines_random("""
            */hello-1.1.zip""")
        assert len([x for x in out.stdout.lines if x.strip()]) == 1
        out = out_devpi("remove", "-y", "hello==1.1", code=200)
        out.stdout.fnmatch_lines_random("deleting release 1.1 of hello")
        out = out_devpi("list")
        assert len([x for x in out.stdout.lines if x.strip()]) == 0
        out = out_devpi("list", "-v")
        assert len([x for x in out.stdout.lines if x.strip()]) == 0

    def test_all_index_option(self, initproj, devpi, out_devpi):
        import re
        initproj("hello-1.0", {"doc": {
            "conf.py": "",
            "index.html": "<html/>"}})
        assert py.path.local("setup.py").check()
        devpi("upload", "--formats", "sdist.zip")
        devpi("upload", "--formats", "sdist.zip,bdist_dumb")
        initproj("hello-1.1", {"doc": {
            "conf.py": "",
            "index.html": "<html/>"}})
        devpi("upload", "--formats", "sdist.zip")

        # remember username
        out = out_devpi("use")
        user = re.search('\(logged in as (.+?)\)', out.stdout.str()).group(1)

        # go to other index
        devpi("use", "root/pypi")
        out = out_devpi("list", "--index", "%s/dev" % user, "hello")
        out.stdout.fnmatch_lines_random("""
            */hello-1.1.zip
            */hello-1.0*
            */hello-1.0.zip""")
        assert len([x for x in out.stdout.lines if x.strip()]) == 3
        out = out_devpi("remove", "--index", "%s/dev" % user, "-y", "hello==1.0", code=200)
        out.stdout.fnmatch_lines_random("deleting release 1.0 of hello")
        out = out_devpi("list", "--index", "%s/dev" % user, "hello")
        out.stdout.fnmatch_lines_random("""
            */hello-1.1.zip""")
        assert len([x for x in out.stdout.lines if x.strip()]) == 1
        out = out_devpi("remove", "--index", "%s/dev" % user, "-y", "hello==1.1", code=200)
        out.stdout.fnmatch_lines_random("deleting release 1.1 of hello")
        out = out_devpi("list", "--index", "%s/dev" % user)
        assert len([x for x in out.stdout.lines if x.strip()]) == 0
        out = out_devpi("list", "--index", "%s/dev" % user, "-v")
        assert len([x for x in out.stdout.lines if x.strip()]) == 0
