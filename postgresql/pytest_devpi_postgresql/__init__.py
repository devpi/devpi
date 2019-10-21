from contextlib import closing
from devpi_postgresql import main
from pluggy import HookimplMarker
import getpass
import py
import pytest
import socket
import subprocess
import tempfile
import time


devpiserver_hookimpl = HookimplMarker("devpiserver")


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
    raise RuntimeError(
        "The port %s on host %s didn't become accessible" % (port, host))


@pytest.yield_fixture(scope="session")
def devpipostgresql_postgresql():
    tmpdir = py.path.local(
        tempfile.mkdtemp(prefix='test-', suffix='-devpi-postgresql'))
    try:
        cap = py.io.StdCaptureFD()
        cap.startall()
        subprocess.check_call(['initdb', tmpdir.strpath])
        cap.reset()
        with tmpdir.join('postgresql.conf').open('w+b') as f:
            f.write(b"\n".join([
                b"fsync = off",
                b"full_page_writes = off",
                b"synchronous_commit = off",
                b"unix_socket_directories = '" + tmpdir.strpath.encode('ascii') + b"'"]))
        host = 'localhost'
        port = get_open_port(host)
        cap = py.io.StdCaptureFD()
        cap.startall()
        p = subprocess.Popen([
            'postgres', '-D', tmpdir.strpath, '-h', host, '-p', str(port)])
        wait_for_port(host, port)
        cap.reset()
        try:
            cap = py.io.StdCaptureFD()
            cap.startall()
            subprocess.check_call([
                'createdb', '-h', host, '-p', str(port), 'devpi'])
            cap.reset()
            settings = dict(host=host, port=port, user=getpass.getuser())
            main.Storage(
                tmpdir, notify_on_commit=False,
                cache_size=10000, settings=settings)
            yield settings
            for conn, db, ts in Storage._connections:
                try:
                    conn.close()
                except AttributeError:
                    pass
            # use a copy of the set, as it might be changed in another thread
            for db in set(Storage._dbs_created):
                try:
                    subprocess.check_call([
                        'dropdb', '-h', Storage.host, '-p', str(Storage.port), db])
                except subprocess.CalledProcessError:
                    pass
        finally:
            p.terminate()
            p.wait()
    finally:
        tmpdir.remove(ignore_errors=True)


class Storage(main.Storage):
    _dbs_created = set()
    _connections = []

    @classmethod
    def _get_test_db(cls, basedir):
        import hashlib
        db = hashlib.md5(
            basedir.strpath.encode('ascii', errors='ignore')).hexdigest()
        if db not in cls._dbs_created:
            subprocess.call([
                'createdb', '-h', cls.host, '-p', str(cls.port),
                '-T', 'devpi', db])
            cls._dbs_created.add(db)
        return db

    @classmethod
    def _get_test_storage_options(cls, basedir):
        cls._db = cls._get_test_db(basedir)
        return ":host=%s,port=%s,user=%s,database=%s" % (
            cls.host, cls.port, cls.user, cls._db)

    @property
    def database(self):
        db = getattr(self, '_db', None)
        if db is None:
            db = self._get_test_db(self.basedir)
        self.__dict__['database'] = db
        return db

    def get_connection(self, *args, **kwargs):
        result = main.Storage.get_connection(self, *args, **kwargs)
        conn = getattr(result, 'thing', result)
        self._connections.append((conn, conn.storage.database, time.time()))
        return result


@pytest.yield_fixture(autouse=True, scope="class")
def devpipostgresql_db_cleanup():
    # this fixture is doing cleanups after tests, so it doesn't yield anything
    yield
    dbs_to_skip = set()
    for i, (conn, db, ts) in reversed(list(enumerate(Storage._connections))):
        sqlconn = getattr(conn, '_sqlconn', None)
        if sqlconn is not None:
            # the connection is still open
            dbs_to_skip.add(db)
            continue
        del Storage._connections[i]
    for db in Storage._dbs_created - dbs_to_skip:
        try:
            subprocess.check_call([
                'dropdb', '-h', Storage.host, '-p', str(Storage.port), db])
        except subprocess.CalledProcessError:
            pass
        else:
            Storage._dbs_created.remove(db)
            if hasattr(Storage, '_db'):
                del Storage._db


@pytest.fixture(autouse=True, scope="session")
def devpipostgresql_devpiserver_storage_backend_mock(request):
    backend = getattr(request.config.option, 'backend', None)
    if backend is None:
        return
    old = main.devpiserver_storage_backend

    @devpiserver_hookimpl
    def devpiserver_storage_backend(settings):
        result = old(settings)
        postgresql = request.getfixturevalue("devpipostgresql_postgresql")
        for k, v in postgresql.items():
            setattr(Storage, k, v)
        result['storage'] = Storage
        return result

    main.devpiserver_storage_backend = devpiserver_storage_backend
