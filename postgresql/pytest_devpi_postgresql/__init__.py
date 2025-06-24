from __future__ import annotations

from contextlib import closing
from contextlib import suppress
from devpi_postgresql import main
from pathlib import Path
from pluggy import HookimplMarker
from certauth.certauth import CertificateAuthority
from shutil import rmtree
from typing import Set
import sys
import os
import getpass
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
    parser.addoption(
        "--backend-postgresql-schema", default="public",
        help="PostgreSQL schema to use for tests (default: public)")


@pytest.fixture(scope="session")
def devpipostgresql_postgresql(request):
    tmpdir = Path(
        tempfile.mkdtemp(prefix='test-', suffix='-devpi-postgresql'))
    tmpdir_path = str(tmpdir)
    try:
        subprocess.check_call(['initdb', tmpdir_path])

        postgresql_conf_lines = [
            "fsync = off",
            "full_page_writes = off",
            "synchronous_commit = off",
            "unix_socket_directories = '{}'".format(tmpdir_path)]

        pg_ssl = request.config.option.backend_postgresql_ssl
        host = 'localhost'

        if pg_ssl:
            # Make certificate authority and server certificate
            ca = CertificateAuthority('Test CA', str(tmpdir / 'ca.pem'),
                                      cert_cache=tmpdir_path)
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
            with tmpdir.joinpath('pg_hba.conf').open('w', encoding='ascii') as f:
                f.write("\n".join([
                    # "local" is for Unix domain socket connections only
                    'local all all trust',
                    # IPv4 local connections:
                    'hostssl all all 127.0.0.1/32 cert',
                    'host all all 127.0.0.1/32 trust']))

        with tmpdir.joinpath('postgresql.conf').open('w+', encoding='ascii') as f:
            f.write("\n".join(postgresql_conf_lines))

        port = get_open_port(host)
        p = subprocess.Popen([
            'postgres', '-D', tmpdir_path, '-h', host, '-p', str(port)])
        wait_for_port(host, port)
        try:
            subprocess.check_call([
                'createdb', '-h', host, '-p', str(port), 'devpi'])
            user = getpass.getuser()

            settings = dict(host=host, port=port, user=user)

            if pg_ssl:
                # Make client certificate for user and authenticate with it.
                client_cert = ca.cert_for_host(user)
                settings['ssl_check_hostname'] = 'yes'
                settings['ssl_ca_certs'] = str(tmpdir / 'ca.pem')
                settings['ssl_certfile'] = client_cert

            # Get schema from command line option
            schema = request.config.option.backend_postgresql_schema
            if schema:
                settings['schema'] = schema

            main.Storage(
                tmpdir_path, notify_on_commit=False,
                cache_size=10000, settings=settings)
            yield settings
            for conn, _is_closing, _db, _ts in Storage._connections:
                with suppress(AttributeError):
                    conn.close()
            # use a copy of the set, as it might be changed in another thread
            for db in set(Storage._dbs_created):
                with suppress(subprocess.CalledProcessError):
                    subprocess.check_call([
                        'dropdb', '--if-exists', '-h', Storage.host, '-p', str(Storage.port), db])
        finally:
            p.terminate()
            p.wait()
    finally:
        rmtree(tmpdir_path)


class Storage(main.Storage):
    _dbs_created: Set[str] = set()
    _connections: list = []
    schema = "public"  # Default schema for tests

    @classmethod
    def _get_test_db(cls, basedir):
        import hashlib
        db = hashlib.md5(  # noqa: S324
            str(basedir).encode('ascii', errors='ignore')).hexdigest()
        if db not in cls._dbs_created:
            subprocess.call([
                'createdb', '-h', cls.host, '-p', str(cls.port),
                '-T', 'devpi', db])
            cls._dbs_created.add(db)
        return db

    @classmethod
    def _get_test_storage_options(cls, basedir):
        db = cls._get_test_db(basedir)
        return ":host=%s,port=%s,user=%s,database=%s,schema=%s" % (
            cls.host, cls.port, cls.user, db, cls.schema)

    @property
    def database(self):
        return self._get_test_db(self.basedir)

    def get_connection(self, *args, **kwargs):
        result = main.Storage.get_connection(self, *args, **kwargs)
        is_closing = isinstance(result, closing)
        conn = result.thing if is_closing else result
        self._connections.append((conn, is_closing, conn.storage.database, time.monotonic()))
        return result


@pytest.fixture(scope="session")
def devpipostgresql_schema(request):
    """Fixture to provide the schema name for PostgreSQL tests."""
    return request.config.option.backend_postgresql_schema


@pytest.fixture(autouse=True, scope="class")
def _devpipostgresql_db_cleanup():
    # this fixture is doing cleanups after tests, so it doesn't yield anything
    yield
    dbs_to_skip = set()
    for i, (conn, _is_closing, db, ts) in reversed(list(enumerate(Storage._connections))):
        sqlconn = getattr(conn, '_sqlconn', None)
        if sqlconn is not None:
            if ((time.monotonic() - ts) > 120):
                conn.close()
            else:
                # the connection is still open
                dbs_to_skip.add(db)
                continue
        del Storage._connections[i]
    for db in Storage._dbs_created - dbs_to_skip:
        try:
            subprocess.check_call([
                'dropdb', '--if-exists', '-h', Storage.host, '-p', str(Storage.port), db])
        except subprocess.CalledProcessError:
            continue
        else:
            Storage._dbs_created.remove(db)


@pytest.fixture(autouse=True, scope="session")
def devpipostgresql_devpiserver_storage_backend_mock(request, server_version):
    from devpi_common.metadata import parse_version
    if server_version < parse_version("6.11.0dev"):
        backend = getattr(request.config.option, 'backend', None)
    else:
        backend = getattr(request.config.option, 'devpi_server_storage_backend', None)
    if backend is None:
        return
    old = main.devpiserver_storage_backend

    @devpiserver_hookimpl
    def devpiserver_storage_backend(settings):
        result = old(settings)
        postgresql = request.getfixturevalue("devpipostgresql_postgresql")
        for k, v in postgresql.items():
            setattr(Storage, k, v)
        # Set schema from fixture if available
        try:
            schema = request.getfixturevalue("devpipostgresql_schema")
            Storage.schema = schema
        except pytest.FixtureLookupError:
            pass
        result['storage'] = Storage
        return result

    main.devpiserver_storage_backend = devpiserver_storage_backend
