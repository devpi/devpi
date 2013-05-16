
import py
import pytest
from devpi.util import url as urlutil
from devpi.test.test import main
from devpi import use

pytest_plugins = "pytester"

@pytest.fixture
def cmd_devpi(cmd_devpi, pypiserverprocess, testdir, monkeypatch):
    assert testdir.tmpdir == py.path.local()
    res = cmd_devpi("use", pypiserverprocess.cfg.url)
    assert res.ret == 0
    return cmd_devpi
    #cfg = pypiserverprocess.cfg
    #assert testdir.tmpdir == py.path.local()
    #api = use.retrieve_api(cfg.url)
    #use.write_api(testdir.tmpdir, api)

class TestFunctional:
    def test_main_nopackage(self, cmd_devpi):
        result = cmd_devpi("test", "--debug", "notexists73", ret=1)
        result.stdout.fnmatch_lines([
            "*could not find/receive*",
        ])

    def test_main_example(self, cmd_devpi, create_and_upload):
        create_and_upload("exa-1.0", filedefs={
           "tox.ini": """
              [testenv]
              commands = python -c "print('ok')"
            """,
        })
        result = cmd_devpi("test", "--debug", "exa")
        assert result.ret == 0
