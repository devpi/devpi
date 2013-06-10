
import py
import pytest
from devpi.util import url as urlutil
from devpi.test.test import main
from devpi.main import check_output

pytest_plugins = "pytester"

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
