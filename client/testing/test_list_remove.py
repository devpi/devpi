import py
import pytest
from devpi.list_remove import *

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
     },
    ["*p1-1.1.tar.gz*", "*p1-1.0.tar.gz*",
    ]),
    ({"1.0": {"+files": {"p1-1.0.tar.gz": "root/dev/pkg/1.0/p1-1.0.tar.gz"},
              "+shadowing": [{"+files":
                    {"p1-1.0.tar.gz": "root/prod/pkg/1.0/p1-1.0.tar.gz"}}]}},
    ["*dev*p1-1.0.tar.gz*", "*prod*p1-1.0.tar.gz"]),
])
def test_out_project(loghub, input, output, monkeypatch):
    from devpi import list_remove
    loghub.current.reconfigure(dict(
                pypisubmit="/post",
                simpleindex="/index",
                index="/root/dev/",
                login="/login",
                ))
    loghub.args.status = False
    monkeypatch.setattr(list_remove, "query_file_status", lambda *args: None)
    out_project(loghub, input)
    matcher = loghub._getmatcher()
    matcher.fnmatch_lines(output)

def test_confirm_delete(loghub, monkeypatch):
    loghub.current.reconfigure(dict(
                pypisubmit="/post",
                simpleindex="/index",
                index="/root/dev/",
                login="/login",
                ))
    monkeypatch.setattr(loghub, "ask_confirm", lambda msg: True)
    data = dict(type="versiondata",
                result={"+files":
                    {"x-1.tar.gz": "root/dev/files/x-1.tar.gz"}})
    assert confirm_delete(loghub, data)


def test_geturl(loghub):
    loghub.current.reconfigure(dict(
                pypisubmit="/post",
                simpleindex="/index",
                index="/root/dev/",
                login="/login",
                ))
    assert get_url(loghub, None).path == "/root/dev/"
    assert get_url(loghub, "pytest").path == "/root/dev/pytest/"
    assert get_url(loghub, "/hpk/rel/pytest").path == "/hpk/rel/pytest/"

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
        devpi("upload", "--formats", "sdist.tgz,bdist_dumb")

        devpi("list", "hello")
        devpi("remove", "-y", "hello")
