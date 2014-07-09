import subprocess

def test_gen_config_all(tmpdir):
    tmpdir.chdir()
    proc = subprocess.Popen(["devpi-server", "--gen-config"])
    res = proc.wait()
    assert res == 0
    b = tmpdir.join("gen-config")
    assert b.join("supervisor-devpi.conf").check()
    assert b.join("nginx-devpi.conf").check()
    assert b.join("crontab").check()

