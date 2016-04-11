from .conftest import get_open_port, wait_for_port
from .functional import TestUserThings as BaseTestUserThings
from .functional import TestIndexThings as BaseTestIndexThings
from .functional import TestMirrorIndexThings as BaseTestMirrorIndexThings
import py
import pytest
import subprocess


nginx_conf_content = """
worker_processes  1;
daemon off;

events {
    worker_connections  32;
}

http {
    default_type  application/octet-stream;
    sendfile        on;
    keepalive_timeout  65;

    include nginx-devpi.conf;
}
"""


@pytest.yield_fixture(scope="module")
def nginx_host_port(request, master_host_port, call_devpi_in_server_directory, server_directory):
    # let xproc find the correct executable instead of py.test
    nginx = py.path.local.sysfind("nginx")
    if nginx is None:
        pytest.skip("No nginx executable found.")
    nginx = str(nginx)

    (host, port) = master_host_port
    orig_dir = server_directory.chdir()
    try:
        call_devpi_in_server_directory(
            ["devpi-server", "--gen-config", "--host", host, "--port", str(port)])
    finally:
        orig_dir.chdir()
    nginx_devpi_conf = server_directory.join("gen-config", "nginx-devpi.conf")
    nginx_port = get_open_port(host)
    nginx_devpi_conf_content = nginx_devpi_conf.read()
    nginx_devpi_conf_content = nginx_devpi_conf_content.replace(
        "listen 80;",
        "listen %s;" % nginx_port)
    nginx_devpi_conf.write(nginx_devpi_conf_content)
    nginx_conf = server_directory.join("gen-config", "nginx.conf")
    nginx_conf.write(nginx_conf_content)
    subprocess.check_call([nginx, "-t", "-c", nginx_conf.strpath])
    p = subprocess.Popen([nginx, "-c", nginx_conf.strpath])
    try:
        wait_for_port(host, nginx_port)
        yield (host, nginx_port)
    finally:
        p.terminate()
        p.wait()


@pytest.yield_fixture
def mapp(makemapp, nginx_host_port):
    from devpi_server.replica import ReplicaThread
    app = makemapp(options=['--master', 'http://%s:%s' % nginx_host_port])
    rt = ReplicaThread(app.xom)
    app.xom.replica_thread = rt
    app.xom.thread_pool.register(rt)
    app.xom.thread_pool.start_one(rt)
    try:
        yield app
    finally:
        app.xom.thread_pool.shutdown()


@pytest.fixture(autouse=True)
def xfail_hanging_tests(request):
    hanging_tests = set([
        'test_push_existing_to_nonvolatile',
        'test_push_existing_to_volatile'])
    if request.function.__name__  in hanging_tests:
        pytest.xfail(reason="test hanging with replica-setup")


@pytest.mark.skipif("not config.option.slow")
class TestUserThings(BaseTestUserThings):
    pass


@pytest.mark.skipif("not config.option.slow")
class TestIndexThings(BaseTestIndexThings):
    pass


@pytest.mark.skipif("not config.option.slow")
class TestMirrorIndexThings(BaseTestMirrorIndexThings):
    pass
