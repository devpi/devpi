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
        from devpi_server.views import API_VERSION
        class reply:
            headers = {"X-DEVPI-API-VERSION": API_VERSION}
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


@pytest.mark.skipif("sys.version_info < (2,7)")
def test_main_devpi_invocation():
    import sys, subprocess
    subprocess.check_call([sys.executable,
                           "-m", "devpi", "--version"])


def test_pkgresources_version_matches_init():
    import devpi
    import pkg_resources
    ver = devpi.__version__
    assert pkg_resources.get_distribution("devpi_client").version == ver


def test_version(loghub):
    from devpi.main import print_version
    loghub.debug = lambda self, *msg: None
    print_version(loghub)
    lines = list(filter(None, loghub._getmatcher().lines))
    assert len(lines) == 1
    assert lines[0].startswith('devpi-client')


@pytest.mark.skipif("sys.version_info < (3,)")
def test_version_server(loghub, url_of_liveserver):
    from devpi.main import print_version
    loghub.debug = lambda self, *msg: None
    loghub.current.configure_fromurl(loghub, url_of_liveserver.url)
    print_version(loghub)
    lines = list(filter(None, loghub._getmatcher().lines))
    assert len(lines) > 2
    names = [x.strip().split()[0] for x in lines]
    assert 'devpi-client' in names
    assert 'devpi-server' in names
