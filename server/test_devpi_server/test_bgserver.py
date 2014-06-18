import sys
import py
import pytest
from devpi_server.main import main


@pytest.mark.skipif("not config.option.slow")
def test_server_commands(tmpdir, monkeypatch):
    monkeypatch.setenv("DEVPI_SERVERDIR", tmpdir)
    monkeypatch.setattr(sys, "argv",
                            [str(py.path.local.sysfind("devpi-server"))])
    main(["devpi-server", "--start", "--port=3499"])
    try:
        main(["devpi-server", "--status"])
        main(["devpi-server", "--log"])
    finally:
        main(["devpi-server", "--stop"])
