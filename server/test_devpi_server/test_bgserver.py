import sys
import random
import py
import pytest
from devpi_server.main import main


@pytest.mark.skipif("not config.option.slow")
def test_server_commands(tmpdir, monkeypatch):
    monkeypatch.setenv("DEVPI_SERVERDIR", tmpdir)
    monkeypatch.setattr(sys, "argv",
                            [str(py.path.local.sysfind("devpi-server"))])
    portopt = "--port=" + str(random.randint(2001, 64000))
    main(["devpi-server", "--start", portopt])
    try:
        main(["devpi-server", "--status"])
        main(["devpi-server", "--log"])
        # make sure we can't start a server if one is already running
        with pytest.raises(SystemExit):
            main(["devpi-server", "--start", portopt])
    finally:
        main(["devpi-server", "--stop"])
