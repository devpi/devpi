import pytest
from devpi.main import verify_reply_version, initmain


def test_initmain():
    with pytest.raises(SystemExit) as excinfo:
        initmain(["devpi"])
    assert excinfo.value.args == (0,)


class TestVerifyAPIVersion:
    def test_noversion(self, loghub):
        class reply:
            headers = {}
        verify_reply_version(loghub, reply)
        matcher = loghub._getmatcher()
        matcher.fnmatch_lines("*assuming API-VERSION 2*")
        verify_reply_version(loghub, reply)
        matcher = loghub._getmatcher()
        assert matcher.str().count("assuming") == 1

    def test_version_ok(self, loghub):
        class reply:
            headers = {"X-DEVPI-API-VERSION": "2"}
        verify_reply_version(loghub, reply)

    def test_version_wrong(self, loghub):
        class reply:
            headers = {"X-DEVPI-API-VERSION": "0"}
        with pytest.raises(SystemExit):
            verify_reply_version(loghub, reply)
        matcher = loghub._getmatcher()
        matcher.fnmatch_lines("*got*0*acceptable*")


def test_subcommands_hook(capsys):
    from devpi.main import get_pluginmanager, parse_args
    from pluggy import HookimplMarker

    calls = []

    class Plugin:
        @HookimplMarker("devpiclient")
        def devpiclient_subcommands(self):
            def myplugincmd_arguments(parser):
                """ myplugindescription """
                calls.append(('myplugincmd_arguments',))

            return [(myplugincmd_arguments, 'myplugincmd', 'mypluginlocation')]

    pm = get_pluginmanager()
    with pytest.raises(SystemExit) as e:
        parse_args(['devpi', '-h'], pm)
    assert e.value.args == (0,)
    (out, err) = capsys.readouterr()
    assert 'patchjson' in out
    assert 'myplugincmd' not in out
    assert 'myplugindescription' not in out
    assert calls == []
    pm.register(Plugin())
    with pytest.raises(SystemExit) as e:
        parse_args(['devpi', '-h'], pm)
    assert e.value.args == (0,)
    (out, err) = capsys.readouterr()
    assert 'patchjson' in out
    assert 'myplugincmd' in out
    assert 'myplugindescription' in out
    assert calls == [('myplugincmd_arguments',)]
    args = parse_args(['devpi', 'myplugincmd'], pm)
    assert args.command == 'myplugincmd'
    assert args.mainloc == 'mypluginlocation'


def test_main_devpi_invocation():
    import subprocess
    import sys
    subprocess.check_call([sys.executable,
                           "-m", "devpi", "--version"])


def test_version(loghub, monkeypatch):
    from devpi.main import get_pluginmanager
    from devpi.main import print_version
    loghub.debug = lambda self, *msg: None
    loghub.pm = get_pluginmanager(load_entry_points=False)
    print_version(loghub)
    lines = list(filter(None, loghub._getmatcher().lines))
    assert len(lines) == 1
    assert lines[0].startswith('devpi-client')


def test_version_server(loghub, url_of_liveserver):
    from devpi.main import print_version
    loghub.debug = lambda self, *msg: None
    loghub.current.configure_fromurl(loghub, url_of_liveserver.url)
    print_version(loghub)
    lines = list(filter(None, loghub._getmatcher().lines))
    assert len(lines) > 2
    loghub._getmatcher().fnmatch_lines("current devpi server:*")
    names = [x.strip().split()[0] for x in lines]
    assert 'devpi-client' in names
    assert 'devpi-server' in names


@pytest.mark.parametrize("devpi_index", ["user/dev", "/user/dev"])
def test_index_option_with_environment_relative_root_current(
        capfd, cmd_devpi, devpi_index, initproj,
        mock_http_api, monkeypatch, reqmock):
    mock_http_api.set(
        "http://devpi/+api", 200, result=dict(
            login="http://devpi/+login",
            authstatus=["noauth", "", []]))
    cmd_devpi("use", "http://devpi")
    monkeypatch.setenv("DEVPI_INDEX", "foo/bar")
    initproj("hello1.1")
    mock_http_api.set(
        "http://devpi/user/dev/+api", 200, result=dict(
            pypisubmit="http://devpi/user/dev/",
            simpleindex="http://devpi/user/dev/+simple/",
            index="http://devpi/user/dev",
            login="http://devpi/+login",
            authstatus=["noauth", "", []]))
    (out, err) = capfd.readouterr()
    reqmock.mockresponse("http://devpi/user/dev/", 200)
    cmd_devpi("upload", "--no-isolation", "--index", devpi_index)
    (out, err) = capfd.readouterr()
    assert "DEVPI_INDEX" not in out
    assert "foo/bar" not in out
    assert "file_upload of hello1.1-0.1.tar.gz to http://devpi/user/dev/" in out.splitlines()


@pytest.mark.parametrize("devpi_index", ["user/dev", "/user/dev"])
def test_index_option_with_environment_relative_user_current(
        capfd, cmd_devpi, devpi_index, initproj,
        mock_http_api, monkeypatch, reqmock):
    mock_http_api.set(
        "http://devpi/user/+api", 200, result=dict(
            login="http://devpi/+login",
            authstatus=["noauth", "", []]))
    cmd_devpi("use", "http://devpi/user")
    monkeypatch.setenv("DEVPI_INDEX", "foo/bar")
    initproj("hello1.1")
    mock_http_api.set(
        "http://devpi/user/dev/+api", 200, result=dict(
            pypisubmit="http://devpi/user/dev/",
            simpleindex="http://devpi/user/dev/+simple/",
            index="http://devpi/user/dev",
            login="http://devpi/+login",
            authstatus=["noauth", "", []]))
    (out, err) = capfd.readouterr()
    reqmock.mockresponse("http://devpi/user/dev/", 200)
    cmd_devpi("upload", "--no-isolation", "--index", devpi_index)
    (out, err) = capfd.readouterr()
    assert "DEVPI_INDEX" not in out
    assert "foo/bar" not in out
    assert "file_upload of hello1.1-0.1.tar.gz to http://devpi/user/dev/" in out.splitlines()


@pytest.mark.parametrize("devpi_index", ["user/dev", "/user/dev"])
def test_index_option_with_environment_relative(
        capfd, cmd_devpi, devpi_index, initproj,
        mock_http_api, monkeypatch, reqmock):
    mock_http_api.set(
        "http://devpi/user/foo/+api", 200, result=dict(
            pypisubmit="http://devpi/user/foo/",
            simpleindex="http://devpi/user/foo/+simple/",
            index="http://devpi/user/foo",
            login="http://devpi/+login",
            authstatus=["noauth", "", []]))
    mock_http_api.set("http://devpi/user/foo?no_projects=", 200, result=dict())
    cmd_devpi("use", "http://devpi/user/foo")
    monkeypatch.setenv("DEVPI_INDEX", "foo/bar")
    initproj("hello1.1")
    mock_http_api.set(
        "http://devpi/user/dev/+api", 200, result=dict(
            pypisubmit="http://devpi/user/dev/",
            simpleindex="http://devpi/user/dev/+simple/",
            index="http://devpi/user/dev",
            login="http://devpi/+login",
            authstatus=["noauth", "", []]))
    (out, err) = capfd.readouterr()
    reqmock.mockresponse("http://devpi/user/dev/", 200)
    cmd_devpi("upload", "--no-isolation", "--index", devpi_index)
    (out, err) = capfd.readouterr()
    assert "DEVPI_INDEX" not in out
    assert "foo/bar" not in out
    assert "file_upload of hello1.1-0.1.tar.gz to http://devpi/user/dev/" in out.splitlines()
