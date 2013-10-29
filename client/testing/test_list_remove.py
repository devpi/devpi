import py
import pytest
from devpi.list_remove import *
from devpi import list_remove

@pytest.mark.parametrize(["input", "output"], [
    (["pkg1", "pkg2"], ["*pkg1*", "*pkg2*"]),
])
def test_out_index(loghub, input, output):
    out_index(loghub, input)
    matcher = loghub._getmatcher()
    matcher.fnmatch_lines(output)

@pytest.mark.parametrize(["input", "output"], [
    ({"1.0": {"+files": {"p1-1.0.tar.gz": "root/dev/pkg/1.0/p1-1.0.tar.gz"},},
      "1.1": {"+files": {"p1-1.1.tar.gz": "root/dev/pkg/1.1/p1-1.1.tar.gz"},},
     }, ["*p1-1.1.tar.gz*", "*p1-1.0.tar.gz*", ]),
    ({"1.0": {"+files": {"p1-1.0.tar.gz": "root/dev/pkg/1.0/p1-1.0.tar.gz"},
              "+shadowing": [{"+files":
                    {"p1-1.0.tar.gz": "root/prod/pkg/1.0/p1-1.0.tar.gz"}}]}},
    ["*dev*p1-1.0.tar.gz*", "*prod*p1-1.0.tar.gz"]),
])

def test_out_project(loghub, input, output, monkeypatch):
    loghub.current.reconfigure(dict(
                simpleindex="/index",
                index="/root/dev/",
                login="/login/",
                ))
    loghub.args.status = False
    loghub.args.all = True
    monkeypatch.setattr(list_remove, "query_file_status", lambda *args: None)
    out_project(loghub, input, parse_requirement("p1"))
    matcher = loghub._getmatcher()
    matcher.fnmatch_lines(output)

    loghub.args.all = False
    out_project(loghub, input, parse_requirement("p1"))
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
        result={"1.0": {
                    "+files": {"x-1.0.tar.gz": "root/dev/files/x-1.0tar.gz"}},
                "1.1": {
                    "+files": {"x-1.1.tar.gz": "root/dev/files/x-1.1.tar.gz"}},
        }
        type = "projectconfig"
    req = parse_requirement("x>=1.1")
    assert confirm_delete(loghub, r, req)
    m = loghub._getmatcher()
    m.fnmatch_lines("""
        *x-1.1.tar.gz*
    """)
    assert "x-1.0" not in req

def test_has_failing_commands():
    assert not has_failing_commands([dict(retcode="0"), dict(retcode="0")])
    assert has_failing_commands([dict(retcode="0"), dict(retcode="1")])

def test_showcommands(loghub):
    loghub.args.failures = True
    show_commands(loghub, [
        {"retcode": "0", "command": ["OK"], "output": "out1"},
        {"retcode": "1", "command": ["fail1"], "output": "FAIL1OUT"}
    ])
    loghub._getmatcher().fnmatch_lines("""
        *OK:*OK*
        *FAIL:*fail1
        *FAIL1OUT*
    """)


class TestList:
    def test_all(self, initproj, devpi):
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
        devpi("list", "hello")
        devpi("remove", "-y", "hello==1.0", code=200)
        devpi("list", "hello")
        devpi("remove", "-y", "hello==1.1", code=200)
