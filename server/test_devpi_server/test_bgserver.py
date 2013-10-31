
from devpi_server.main import main

def test_server_commands(tmpdir, monkeypatch):
    monkeypatch.setenv("DEVPI_SERVERDIR", tmpdir)
    main(["devpi-server", "--start", "--port=3499"])
    try:
        main(["devpi-server", "--status"])
        main(["devpi-server", "--log"])
    finally:
        main(["devpi-server", "--stop"])
