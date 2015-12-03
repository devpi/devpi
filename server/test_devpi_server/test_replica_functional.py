from .functional import TestUserThings as BaseTestUserThings
from .functional import TestIndexThings as BaseTestIndexThings
from contextlib import closing
import py
import pytest
import socket
import tempfile
import time


def get_open_port(host):
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        s.bind((host, 0))
        s.listen(1)
        port = s.getsockname()[1]
    return port


def wait_for_port(host, port, timeout=60):
    while timeout > 0:
        with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
            s.settimeout(1)
            if s.connect_ex((host, port)) == 0:
                return
        time.sleep(1)
        timeout -= 1


@pytest.yield_fixture(scope="session")
def master_host_port(request):
    def devpi(args):
        from devpi_server.main import main
        import os
        import sys
        notset = object()
        orig_sys_argv = sys.argv
        orig_env_devpi_serverdir = os.environ.get("DEVPI_SERVERDIR", notset)
        try:
            sys.argv = [devpi_server]
            os.environ['DEVPI_SERVERDIR'] = srvdir.strpath
            main(args)
        finally:
            sys.argv = orig_sys_argv
            if orig_env_devpi_serverdir is notset:
                del os.environ["DEVPI_SERVERDIR"]
            else:
                os.environ["DEVPI_SERVERDIR"] = orig_env_devpi_serverdir
    srvdir = py.path.local(
        tempfile.mkdtemp(prefix='test-', suffix='-devpi-master'))
    devpi_server = str(py.path.local.sysfind("devpi-server"))
    # let xproc find the correct executable instead of py.test
    host = 'localhost'
    port = get_open_port(host)
    devpi(["devpi-server", "--start", "--host", host, "--port", str(port),
          "--serverdir", srvdir.strpath])
    try:
        wait_for_port(host, port)
        yield (host, port)
    finally:
        try:
            devpi(["devpi-server", "--stop"])
        finally:
            srvdir.remove(ignore_errors=True)


@pytest.fixture
def mapp(makemapp, master_host_port):
    from devpi_server.replica import ReplicaThread
    app = makemapp(options=['--master', 'http://%s:%s' % master_host_port])
    rt = ReplicaThread(app.xom)
    app.xom.replica_thread = rt
    app.xom.thread_pool.register(rt)
    app.xom.thread_pool.start_one(rt)
    return app


@pytest.mark.skipif("not config.option.slow")
class TestUserThings(BaseTestUserThings):
    # modifies root password, which breaks following tests
    def test_password_setting_admin(self):
        pass


@pytest.mark.skipif("not config.option.slow")
class TestIndexThings(BaseTestIndexThings):
    # modifies root password, which breaks following tests
    def test_create_index_default_allowed(self):
        pass

    # hangs
    def test_push_existing_to_nonvolatile(self):
        pass

    # hangs
    def test_push_existing_to_volatile(self):
        pass
