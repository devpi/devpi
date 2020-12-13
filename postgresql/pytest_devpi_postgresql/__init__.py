from contextlib import closing
from devpi_postgresql import main
from pluggy import HookimplMarker
from certauth.certauth import CertificateAuthority
import sys
import os
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


def pytest_addoption(parser):
    parser.addoption(
        "--backend-postgresql-ssl", action="store_true",
        help="make SSL connections to PostgreSQL")


@pytest.fixture(scope="session")
def devpipostgresql_postgresql(request):
    tmpdir = py.path.local(
        tempfile.mkdtemp(prefix='test-', suffix='-devpi-postgresql'))
    try:
        cap = py.io.StdCaptureFD()
        cap.startall()
        subprocess.check_call(['initdb', tmpdir.strpath])
        cap.reset()

        postgresql_conf_lines = [
            "fsync = off",
            "full_page_writes = off",
            "synchronous_commit = off",
            "unix_socket_directories = '{}'".format(tmpdir.strpath)]

        pg_ssl = request.config.option.backend_postgresql_ssl
        host = 'localhost'

        if pg_ssl:
            # Make certificate authority and server certificate
            ca = CertificateAuthority('Test CA', tmpdir.join('ca.pem').strpath,
                                      cert_cache=tmpdir.strpath)
            server_cert = ca.cert_for_host(host)
            if not sys.platform.startswith("win"):
                # Postgres requires restrictive permissions on private key.
                os.chmod(server_cert, 0o600)

            postgresql_conf_lines.extend([
                "ssl = on",
                "ssl_cert_file = '{}'".format(server_cert),
                "ssl_key_file = '{}'".format(server_cert),
                "ssl_ca_file = 'ca.pem'"])

            # Require SSL connections to be authenticated by client certificates.
            with tmpdir.join('pg_hba.conf').open('w', encoding='ascii') as f:
                f.write("\n".join([
                    # "local" is for Unix domain socket connections only
                    'local all all trust',
                    # IPv4 local connections:
                    'hostssl all all 127.0.0.1/32 cert',
                    'host all all 127.0.0.1/32 trust']))

        with tmpdir.join('postgresql.conf').open('w+', encoding='ascii') as f:
            f.write("\n".join(postgresql_conf_lines))

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
            user = getpass.getuser()

            settings = dict(host=host, port=port, user=user)

            if pg_ssl:
                # Make client certificate for user and authenticate with it.
                client_cert = ca.cert_for_host(user)
                settings['ssl_check_hostname'] = 'yes'
                settings['ssl_ca_certs'] = tmpdir.join('ca.pem').strpath
                settings['ssl_certfile'] = client_cert

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


@pytest.fixture(autouse=True, scope="class")
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
