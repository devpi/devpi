import subprocess

def test_gen_config_all():
    proc = subprocess.Popen(["devpi-server", "--gen-config"])
    res = proc.wait()
    assert res == 0
