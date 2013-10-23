
import pytest
import py

from devpi_server.venv import *

@pytest.mark.skipif("not config.option.slow or sys.version_info >= (3,0)")
def test_create_server_venv(tmpdir):
    tw = py.io.TerminalWriter()
    venv = create_server_venv(tw, "1.1", tmpdir)
    out = venv.check_output(["devpi-server", "--version"]).strip()
    assert out == "1.1"

