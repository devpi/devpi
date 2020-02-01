import subprocess
import pytest


@pytest.mark.skipif("sys.platform == 'win32'")
def test_gen_config_all(tmpdir):
    tmpdir.chdir()
    proc = subprocess.Popen(["devpi-gen-config"])
    res = proc.wait()
    assert res == 0
    b = tmpdir.join("gen-config")
    assert b.join("devpi.service").check()
    assert b.join("supervisord.conf").check()
    assert b.join("supervisor-devpi.conf").check()
    assert b.join("nginx-devpi.conf").check()
    assert b.join("crontab").check()
    assert b.join("launchd-macos.txt").check()
    assert b.join("net.devpi.plist").check()
    assert b.join("windows-service.txt").check()
