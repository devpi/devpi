import pytest

def test_dryrun(cmd_devpi):
    cmd_devpi("quickstart", "--dry-run")

def test_functional(cmd_devpi, monkeypatch, tmpdir):
    monkeypatch.setenv("DEVPI_SERVER", tmpdir.join("serverdata"))
    cmd_devpi("quickstart")
    try:
        with pytest.raises(SystemExit):
            cmd_devpi("server", "quickstart")
    finally:
        cmd_devpi("server", "--stop")
