from devpi_common.types import cached_property
try:
    from devpi_server import interfaces as ds_interfaces
except ImportError:
    ds_interfaces = None
from devpi_server.fileutil import dumps, loads
try:
    from devpi_server.keyfs import RelpathInfo
    from devpi_server.keyfs import get_relpath_at
except ImportError:
    pass
from devpi_server.log import threadlog, thread_push_log, thread_pop_log
from devpi_server.readonly import ReadonlyView
from devpi_server.readonly import ensure_deeply_readonly, get_mutable_deepcopy
from functools import partial
from pluggy import HookimplMarker
from repoze.lru import LRUCache
from tempfile import SpooledTemporaryFile as SpooledTemporaryFileBase
from zope.interface import Interface
from zope.interface import implementer
import contextlib
import os
import pg8000.native
import py
import time
from devpi_server.model import ensure_boolean
import ssl


for name in ('IStorageConnection2', 'IStorageConnection'):
    IStorageConnection2 = getattr(ds_interfaces, name, Interface)
    if IStorageConnection2 is not Interface:
        break


absent = object()


devpiserver_hookimpl = HookimplMarker("devpiserver")


class SpooledTemporaryFile(SpooledTemporaryFileBase):
    # some missing methods
    def readable(self):
        return self._file.readable()

    def readinto(self, buffer):
        return self._file.readinto(buffer)

    def seekable(self):
        return self._file.seekable()

    def writable(self):
        return self._file.writable()


@implementer(IStorageConnection2)
class Connection:
    def __init__(self, sqlconn, storage):
        self._sqlconn = sqlconn
        self.dirty_files = {}
        self.changes = {}
        self.storage = storage
        self._changelog_cache = storage._changelog_cache

    def close(self):
        if hasattr(self, "_sqlconn"):
            self._sqlconn.close()
            del self._sqlconn
        if hasattr(self, "storage"):
            del self.storage

    def begin(self):
        self._sqlconn.run("START TRANSACTION")
        return self._sqlconn

    def commit(self):
        self._sqlconn.run("COMMIT")

    def rollback(self):
        self._sqlconn.run("ROLLBACK")

    def fetchone(self, q, **kw):
        row = self._sqlconn.run(q, **kw)
        if not row:
            return None
        (res,) = row
        return res

    def fetchscalar(self, q, **kw):
        row = self._sqlconn.run(q, **kw)
        if not row:
            return None
        ((res,),) = row
        return res

    @cached_property
    def last_changelog_serial(self):
        return self.db_read_last_changelog_serial()

    def db_read_last_changelog_serial(self):
        q = 'SELECT MAX(serial) FROM changelog'
        res = self.fetchscalar(q)
        return -1 if res is None else res

    def db_read_typedkey(self, relpath):
        q = "SELECT keyname, serial FROM kv WHERE key = :relpath"
        res = self.fetchone(q, relpath=relpath)
        if res is None:
            raise KeyError(relpath)
        (keyname, serial) = res
        return (keyname, serial)

    def get_relpath_at(self, relpath, serial):
        result = self._changelog_cache.get((serial, relpath), absent)
        if result is absent:
            changes = self._changelog_cache.get(serial, absent)
            if changes is not absent and relpath in changes:
                (keyname, back_serial, value) = changes[relpath]
                result = (serial, back_serial, value)
        if result is absent:
            result = get_relpath_at(self, relpath, serial)
        self._changelog_cache.put((serial, relpath), result)
        return result

    def iter_relpaths_at(self, typedkeys, at_serial):
        keynames = frozenset(k.name for k in typedkeys)
        keyname_id_values = {"keynameid%i" % i: k for i, k in enumerate(keynames)}
        q = """
            SELECT key, keyname, serial
            FROM kv
            WHERE serial=:serial AND keyname IN (:keynames)
        """
        q = q.replace(':keynames', ", ".join(':' + x for x in keyname_id_values))
        for serial in range(at_serial, -1, -1):
            rows = self._sqlconn.run(q, serial=serial, **keyname_id_values)
            if not rows:
                continue
            changes = self._changelog_cache.get(serial, absent)
            if changes is absent:
                changes = loads(
                    self.get_raw_changelog_entry(serial))[0]
            for relpath, keyname, serial in rows:
                (keyname, back_serial, val) = changes[relpath]
                yield RelpathInfo(
                    relpath=relpath, keyname=keyname,
                    serial=serial, back_serial=back_serial,
                    value=val)

    def io_file_os_path(self, path):
        return None

    def io_file_exists(self, path):
        assert not os.path.isabs(path)
        f = self.dirty_files.get(path, absent)
        if f is not absent:
            return f is not None
        q = "SELECT path FROM files WHERE path = :path"
        return bool(self.fetchscalar(q, path=path))

    def io_file_set(self, path, content):
        assert not os.path.isabs(path)
        assert not path.endswith("-tmp")
        f = self.dirty_files.get(path, None)
        if f is None:
            f = SpooledTemporaryFile(max_size=1048576)
        f.write(content)
        f.seek(0)
        self.dirty_files[path] = f

    def io_file_open(self, path):
        f = self.dirty_files.get(path, absent)
        if f is None:
            raise IOError()
        if f is absent:
            return py.io.BytesIO(self.io_file_get(path))
        f.seek(0)
        return f

    def io_file_get(self, path):
        assert not os.path.isabs(path)
        f = self.dirty_files.get(path, absent)
        if f is None:
            raise IOError()
        elif f is not absent:
            pos = f.tell()
            f.seek(0)
            content = f.read()
            f.seek(pos)
            return content
        q = "SELECT data FROM files WHERE path = :path"
        res = self.fetchscalar(q, path=path)
        if res is None:
            raise IOError()
        return res

    def io_file_size(self, path):
        assert not os.path.isabs(path)
        f = self.dirty_files.get(path, absent)
        if f is None:
            raise IOError()
        elif f is not absent:
            pos = f.tell()
            size = f.seek(0, 2)
            f.seek(pos)
            return size
        q = "SELECT size FROM files WHERE path = :path"
        return self.fetchscalar(q, path=path)

    def io_file_delete(self, path):
        assert not os.path.isabs(path)
        f = self.dirty_files.pop(path, None)
        if f is not None:
            f.close()
        self.dirty_files[path] = None

    def get_raw_changelog_entry(self, serial):
        # because a sequence is used for the next serial, there might be
        # missing serials in the changelog table if there was a conflict
        # during commit
        # this query makes sure we return an empty changelog for missing
        # serials, but only if the serial wasn't used yet by comparing with
        # max(serial) of changelog
        q = r"""
            SELECT
                COALESCE(
                    data,
                    'JK\000\000\000\000@\000\000\000\002Q'::BYTEA) AS data
            FROM changelog
            RIGHT OUTER JOIN (
                SELECT
                    :serial::BIGINT AS serial
                WHERE (
                    :serial::BIGINT <= (SELECT max(serial) FROM changelog))
                ) AS serial
            ON changelog.serial=serial.serial;"""
        return self.fetchscalar(q, serial=serial)

    def get_changes(self, serial):
        changes = self._changelog_cache.get(serial)
        if changes is None:
            data = self.get_raw_changelog_entry(serial)
            changes, rel_renames = loads(data)
            # make values in changes read only so no calling site accidentally
            # modifies data
            changes = ensure_deeply_readonly(changes)
            self.cache_commit_changes(serial, changes)
        return changes

    def cache_commit_changes(self, serial, changes):
        assert isinstance(changes, ReadonlyView)
        self._changelog_cache.put(serial, changes)

    def write_transaction(self):
        return Writer(self.storage, self)

    def _file_write(self, path, f):
        assert not os.path.isabs(path)
        assert not path.endswith("-tmp")
        q = """
            INSERT INTO files(path, size, data)
                VALUES (:path, :size, :data);"""
        f.seek(0)
        content = f.read()
        f.close()
        self._sqlconn.run(
            q, path=path, size=len(content), data=pg8000.Binary(content))

    def _file_delete(self, path):
        assert not os.path.isabs(path)
        assert not path.endswith("-tmp")
        q = "DELETE FROM files WHERE path = :path"
        self._sqlconn.run(q, path=path)

    def _lock(self):
        q = 'SELECT pg_advisory_xact_lock(1);'
        self._sqlconn.run(q)

    def _write_dirty_files(self):
        for path, f in self.dirty_files.items():
            if f is None:
                self._file_delete(path)
            else:
                # delete first to avoid conflict
                self._file_delete(path)
                self._file_write(path, f)
        self.dirty_files.clear()

    def commit_files_without_increasing_serial(self):
        self.begin()
        try:
            self._lock()
            self._write_dirty_files()
        except BaseException:
            self.rollback()
            raise
        else:
            self.commit()


class Storage:
    SSL_OPT_KEYS = ("ssl_check_hostname", "ssl_ca_certs", "ssl_certfile", "ssl_keyfile")
    database = "devpi"
    host = "localhost"
    port = "5432"
    unix_sock = None
    user = "devpi"
    password = None
    ssl_context = None
    expected_schema = dict(
        index=dict(
            kv_serial_idx="""
                CREATE INDEX kv_serial_idx ON kv (serial);
            """),
        sequence=dict(
            changelog_serial_seq="""
                CREATE SEQUENCE changelog_serial_seq
                AS BIGINT
                MINVALUE 0
                START :startserial;
            """),
        table=dict(
            changelog="""
                CREATE TABLE changelog (
                    serial INTEGER PRIMARY KEY,
                    data BYTEA NOT NULL
                )
            """,
            kv="""
                CREATE TABLE kv (
                    key TEXT NOT NULL PRIMARY KEY,
                    keyname TEXT,
                    serial INTEGER
                )
            """,
            files="""
                CREATE TABLE files (
                    path TEXT PRIMARY KEY,
                    size INTEGER NOT NULL,
                    data BYTEA NOT NULL
                )
            """))

    def __init__(self, basedir, notify_on_commit, cache_size, settings=None):
        if settings is None:
            settings = {}
        for key in ("database", "host", "port", "unix_sock", "user", "password"):
            if key in settings:
                setattr(self, key, settings[key])

        if any(key in settings for key in self.SSL_OPT_KEYS):
            self.ssl_context = ssl_context = ssl.create_default_context(
                cafile=settings.get('ssl_ca_certs'))

            if 'ssl_certfile' in settings:
                ssl_context.load_cert_chain(settings['ssl_certfile'],
                                            keyfile=settings.get('ssl_keyfile'))

            check_hostname = settings.get('ssl_check_hostname')
            if check_hostname is not None and not ensure_boolean(check_hostname):
                ssl_context.check_hostname = False

        self.basedir = basedir
        self._notify_on_commit = notify_on_commit
        self._changelog_cache = LRUCache(cache_size)  # is thread safe
        self.last_commit_timestamp = time.time()
        self.ensure_tables_exist()

    def perform_crash_recovery(self):
        pass

    def get_connection(self, closing=True, write=False):
        sqlconn = pg8000.native.Connection(
            user=self.user,
            database=self.database,
            host=self.host,
            port=int(self.port),
            unix_sock=self.unix_sock,
            password=self.password,
            ssl_context=self.ssl_context,
            timeout=60)
        sqlconn.text_factory = bytes
        conn = Connection(sqlconn, self)
        if closing:
            return contextlib.closing(conn)
        return conn

    def _reflect_schema(self):
        result = {}
        with self.get_connection() as conn:
            sqlconn = conn.begin()
            rows = sqlconn.run("""
                SELECT tablename FROM pg_tables WHERE schemaname='public';""")
            for row in rows:
                result.setdefault("table", {})[row[0]] = ""
            rows = sqlconn.run("""
                SELECT indexname FROM pg_indexes WHERE schemaname='public';""")
            for row in rows:
                result.setdefault("index", {})[row[0]] = ""
            rows = sqlconn.run("""
                SELECT sequencename FROM pg_sequences WHERE schemaname='public';""")
            for row in rows:
                result.setdefault("sequence", {})[row[0]] = ""
        return result

    def ensure_tables_exist(self):
        schema = self._reflect_schema()
        missing = dict()
        for kind, objs in self.expected_schema.items():
            for name, q in objs.items():
                if name not in schema.get(kind, set()):
                    missing.setdefault(kind, dict())[name] = q
        if not missing:
            return
        with self.get_connection() as conn:
            sqlconn = conn.begin()
            if not schema:
                threadlog.info("DB: Creating schema")
            else:
                threadlog.info("DB: Updating schema")
            if "changelog" not in missing.get("table", {}):
                kw = dict(startserial=conn.db_read_last_changelog_serial() + 1)
            else:
                kw = dict(startserial=0)
            for kind in ('table', 'index', 'sequence'):
                objs = missing.pop(kind, {})
                for name in list(objs):
                    q = objs.pop(name)
                    for k, v in kw.items():
                        q = q.replace(f":{k}", pg8000.native.literal(v))
                    sqlconn.run(q)
                assert not objs
            conn.commit()
        assert not missing


@devpiserver_hookimpl
def devpiserver_storage_backend(settings):
    return dict(
        storage=partial(Storage, settings=settings),
        name="pg8000",
        description="Postgresql backend")


class Writer:
    def __init__(self, storage, conn):
        self.conn = conn
        self.storage = storage

    def record_set(self, typedkey, value=None, back_serial=None):
        """ record setting typedkey to value (None means it's deleted) """
        assert not isinstance(value, ReadonlyView), value
        # at __exit__ time we write out changes to the _changelog_cache
        # so we protect here against the caller modifying the value later
        value = get_mutable_deepcopy(value)
        self.changes[typedkey.relpath] = (typedkey.name, back_serial, value)

    def _db_write_typedkey(self, relpath, name, serial):
        q = """
            INSERT INTO kv(key, keyname, serial)
                VALUES (:relpath, :name, :serial)
            ON CONFLICT (key) DO UPDATE
                SET keyname = EXCLUDED.keyname, serial = EXCLUDED.serial;"""
        self.conn._sqlconn.run(q, relpath=relpath, name=name, serial=serial)

    def _write_changelog_entry(self, serial, entry):
        threadlog.debug("writing changelog for serial %s", serial)
        q = """
            INSERT INTO changelog (serial, data) VALUES (:serial, :data);"""
        data = dumps(entry)
        self.conn._sqlconn.run(q, serial=serial, data=pg8000.Binary(data))

    def __enter__(self):
        self.conn.begin()
        self.conn._lock()
        q = """SELECT nextval('changelog_serial_seq');"""
        self.commit_serial = self.conn.fetchscalar(q)
        self.log = thread_push_log("fswriter%s:" % self.commit_serial)
        self.changes = {}
        return self

    def __exit__(self, cls, val, tb):
        commit_serial = self.commit_serial
        try:
            del self.commit_serial
            if cls is None:
                self.conn._write_dirty_files()
                for relpath, (keyname, back_serial, value) in self.changes.items():
                    if back_serial is None:
                        try:
                            (_, back_serial) = self.conn.db_read_typedkey(relpath)
                        except KeyError:
                            back_serial = -1
                        # update back_serial for _write_changelog_entry
                        self.changes[relpath] = (keyname, back_serial, value)
                    self._db_write_typedkey(relpath, keyname, commit_serial)
                entry = (self.changes, [])
                self._write_changelog_entry(commit_serial, entry)
                self.conn.commit()
                message = "committed: keys: %s"
                args = [",".join(map(repr, list(self.changes)))]
                self.log.info("commited at %s", commit_serial)
                self.log.debug(message, *args)
                self.storage._notify_on_commit(commit_serial)
            else:
                self.conn.rollback()
                self.log.info("roll back in %s", commit_serial)
            del self.conn
            del self.storage
            del self.log
        except BaseException:
            self.conn.rollback()
            raise
        finally:
            thread_pop_log("fswriter%s:" % commit_serial)
