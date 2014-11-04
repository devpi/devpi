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
