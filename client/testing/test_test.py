
import pytest
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

def test_fallback_ini(makehub, tmpdir, pseudo_current):
    p = tmpdir.ensure("mytox.ini")
    hub = makehub(["test", "--fallback-ini", str(p), "somepkg"])
    index = DevIndex(hub, tmpdir, pseudo_current)
    args = index.get_tox_args(unpack_path=tmpdir)
    assert contains_sublist(args, ["-c", str(p)])
    p2 = tmpdir.ensure("tox.ini")
    args = index.get_tox_args(unpack_path=tmpdir)
    assert contains_sublist(args, ["-c", str(p2)])

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

