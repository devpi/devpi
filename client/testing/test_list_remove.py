import os, sys
import json
import py
import pytest
import types
from mock import Mock
from devpi.list_remove import out_index
from devpi.list_remove import out_project
from devpi.list_remove import getjson
from devpi.list_remove import confirm_delete

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
    ])
])
def test_out_project(loghub, input, output):
    loghub.current.reconfigure(dict(
                pypisubmit="/post",
                simpleindex="/index",
                index="/root/dev/",
                login="/login",
                ))
    out_project(loghub, input, "p1")
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


def test_getjson(loghub):
    loghub.current.reconfigure(dict(
                pypisubmit="/post",
                simpleindex="/index",
                index="/root/dev/",
                login="/login",
                ))
    loghub.http_api = Mock(autospec=loghub.__class__.http_api)
    getjson(loghub, None)
    loghub.http_api.assert_called_once_with("get", "/root/dev/", quiet=True)
    loghub.http_api = Mock(autospec=loghub.__class__.http_api)
    getjson(loghub, "proj")
    loghub.http_api.assert_called_once_with("get", "/root/dev/proj/",
                                            quiet=True)

class TestList:
    def test_all(self, initproj, devpi):
        initproj("hello-1.0", {"doc": {
            "conf.py": "",
            "index.html": "<html/>"}})
        assert py.path.local("setup.py").check()
        devpi("upload", "--formats", "sdist.tbz")
        devpi("upload", "--formats", "sdist.tgz,bdist_dumb")

        devpi("list", "hello")
        devpi("remove", "-y", "hello")
