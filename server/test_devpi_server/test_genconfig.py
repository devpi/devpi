import subprocess
import pytest


@pytest.mark.slow
@pytest.mark.skipif("sys.platform == 'win32'")
def test_gen_config_all(tmpdir):
    tmpdir.chdir()
    proc = subprocess.Popen(["devpi-gen-config"])  # noqa: S603,S607
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


@pytest.mark.slow
@pytest.mark.skipif("sys.platform == 'win32'")
def test_gen_config_caching(tmpdir):
    tmpdir.chdir()
    proc = subprocess.Popen(["devpi-gen-config"])  # noqa: S603,S607
    res = proc.wait()
    assert res == 0
    b = tmpdir.join("gen-config")
    config = b.join("nginx-devpi-caching.conf").read()
    assert 'proxy_cache_path' in config
    assert config.count('$bypass_caching') > 1
    config = b.join("nginx-devpi.conf").read()
    assert 'proxy_cache_path' not in config
    assert config.count('$bypass_caching') == 0


@pytest.mark.slow
@pytest.mark.skipif("sys.platform == 'win32'")
def test_gen_config_mirror_cache_expiry(tmpdir):
    tmpdir.chdir()
    proc = subprocess.Popen([  # noqa: S603,S607
        "devpi-gen-config",
        "--mirror-cache-expiry=33"])
    res = proc.wait()
    assert res == 0
    b = tmpdir.join("gen-config")
    config = b.join("nginx-devpi-caching.conf").read()
    assert 'proxy_cache_valid 200 33s;' in config
