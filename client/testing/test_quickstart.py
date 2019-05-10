import py
import pytest
import subprocess


@pytest.mark.skipif("config.option.fast or sys.version_info.major < 3")
def test_dryrun(cmd_devpi):
    cmd_devpi("quickstart", "--dry-run")


@pytest.mark.skipif("config.option.fast or sys.version_info.major < 3")
def test_functional(cmd_devpi, monkeypatch, server_version, tmpdir):
    from pkg_resources import parse_version
    if server_version >= parse_version('4.7.0.dev'):
        monkeypatch.setenv("DEVPISERVER_SERVERDIR", tmpdir.join("server").strpath)
    else:
        monkeypatch.setenv("DEVPI_SERVERDIR", tmpdir.join("server").strpath)
    monkeypatch.setenv("DEVPI_CLIENTDIR", tmpdir.join("client").strpath)
    cmd_devpi("quickstart")
    try:
        hub = cmd_devpi("quickstart", code=-2)
        assert isinstance(hub.sysex, SystemExit)
    finally:
        p = py.path.local.sysfind("devpi-server")
        subprocess.check_call([str(p), "--stop"])
