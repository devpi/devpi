import sys
import os
import random
import py
import pytest
from devpi_server.main import main
from devpi_server.bgserver import no_proxy


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


def test_no_proxy():
    original = {
        "no_proxy": "no_proxy",
        "NO_PROXY": "NO_PROXY",
    }
    os.environ.update(original)

    with no_proxy("localhost:8080"):
        assert os.environ["no_proxy"] == "localhost:8080"
        assert "NO_PROXY" not in os.environ

    for k, v in original.items():
        assert os.environ[k] == v
