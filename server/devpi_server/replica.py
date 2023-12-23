import os
import contextlib
import io
import itsdangerous
import secrets
import threading
import time
import traceback
from contextlib import suppress
import warnings
from functools import partial
from pluggy import HookimplMarker
from pyramid.httpexceptions import HTTPNotFound, HTTPAccepted, HTTPBadRequest
from pyramid.httpexceptions import HTTPForbidden
from pyramid.view import view_config
from pyramid.response import Response
from repoze.lru import LRUCache
from devpi_common.types import cached_property
from devpi_common.url import URL
from devpi_common.validation import normalize_name
from webob.headers import EnvironHeaders, ResponseHeaders

from . import mythread
from .config import hookimpl
from .exceptions import lazy_format_exception
from .filestore import ChecksumError
from .filestore import FileEntry
from .fileutil import buffered_iterator
from .fileutil import dumps, load, loads
from .log import thread_push_log, threadlog
from .main import fatal
from .views import FileStreamer
from .views import H_MASTER_UUID
from .views import H_PRIMARY_UUID
from .views import make_uuid_headers
from .model import UpstreamError


devpiweb_hookimpl = HookimplMarker("devpiweb")


H_REPLICA_UUID = "X-DEVPI-REPLICA-UUID"
H_REPLICA_OUTSIDE_URL = "X-DEVPI-REPLICA-OUTSIDE-URL"
H_REPLICA_FILEREPL = "X-DEVPI-REPLICA-FILEREPL"
H_EXPECTED_MASTER_ID = "X-DEVPI-EXPECTED-MASTER-ID"
H_EXPECTED_PRIMARY_ID = "X-DEVPI-EXPECTED-PRIMARY-ID"

MAX_REPLICA_BLOCK_TIME = 30.0
REPLICA_USER_NAME = "+replica"
REPLICA_REQUEST_TIMEOUT = MAX_REPLICA_BLOCK_TIME * 1.25
REPLICA_MULTIPLE_TIMEOUT = REPLICA_REQUEST_TIMEOUT / 2
REPLICA_AUTH_MAX_AGE = REPLICA_REQUEST_TIMEOUT + 0.1
REPLICA_CONTENT_TYPE = "application/x-devpi-replica-changes"
REPLICA_ACCEPT_STREAMING = f"{REPLICA_CONTENT_TYPE}, application/octet-stream; q=0.9"
MAX_REPLICA_CHANGES_SIZE = 5 * 1024 * 1024


notset = object()


class IndexType:
    # class for the index type to get correct sort order
    def __init__(self, index_type):
        if isinstance(index_type, IndexType):
            index_type = index_type._index_type
        self._index_type = index_type

    def __hash__(self):
        return hash(self._index_type)

    def __repr__(self):
        return f"<IndexType {self._index_type!r}>"

    def __lt__(self, other):
        if self._index_type == other._index_type:
            return False
        if self._index_type is None:
            # deleted are lowest priority, so come last
            return False
        if other._index_type is None:
            # the other is deleted, so we come first
            return True
        if self._index_type == "mirror":
            # mirrors are just before deleted
            return False
        if other._index_type == "mirror":
            # the other is a mirror, so we come before
            return True
        # everything else is by alphabet
        return self._index_type < other._index_type

    def __eq__(self, other):
        return self._index_type == other._index_type


def get_auth_serializer(config):
    return itsdangerous.TimedSerializer(config.get_replica_secret())


def log_replica_token_error(request, msg):
    if getattr(request, '__devpi_replica_token_warned', None) is None:
        request.log.error(msg)
        request.__devpi_replica_token_warned = True


class ReplicaIdentity:
    def __init__(self):
        self.username = REPLICA_USER_NAME
        self.groups = []


@hookimpl(tryfirst=True)
def devpiserver_get_identity(request, credentials):
    # the DummyRequest class used in testing doesn't have the attribute
    authorization = request.authorization
    if not authorization:
        return None
    if authorization.authtype != 'Bearer':
        return None
    if H_REPLICA_UUID not in request.headers:
        return None
    if not request.registry["xom"].is_primary():
        log_replica_token_error(
            request, "Replica token detected, but role isn't primary.")
        return None
    auth_serializer = get_auth_serializer(request.registry["xom"].config)
    try:
        sent_uuid = auth_serializer.loads(
            authorization.params, max_age=REPLICA_AUTH_MAX_AGE)
    except itsdangerous.SignatureExpired:
        raise HTTPForbidden("Authorization expired.")
    except itsdangerous.BadData:
        raise HTTPForbidden("Authorization malformed.")
    if not secrets.compare_digest(request.headers[H_REPLICA_UUID], sent_uuid):
        raise HTTPForbidden("Wrong authorization value.")
    return ReplicaIdentity()


@hookimpl(tryfirst=True)
def devpiserver_auth_request(request, userdict, username, password):
    # no other plugin must be able to authenticate the special REPLICA_USER_NAME
    # so instead of returning status unknown, we will raise HTTPForbidden
    if username == REPLICA_USER_NAME:
        raise HTTPForbidden("Authorization malformed.")


class ReadableIterabel(io.RawIOBase):
    def __init__(self, iterable):
        self.iterable = iterable
        self.chunk = None
        self.chunk_pos = 0
        self.chunk_size = 0

    def readable(self):
        return True

    def readinto(self, b):
        if self.chunk is None:
            self.chunk = next(self.iterable)
            self.chunk_pos = 0
            self.chunk_size = len(self.chunk)
        chunk_remaining = self.chunk_size - self.chunk_pos
        to_copy = min(len(b), chunk_remaining)
        b[:to_copy] = self.chunk[self.chunk_pos:self.chunk_pos + to_copy]
        self.chunk_pos += to_copy
        if self.chunk_pos == self.chunk_size:
            self.chunk = None
        return to_copy


class PrimaryChangelogRequest:
    MAX_REPLICA_BLOCK_TIME = MAX_REPLICA_BLOCK_TIME
    MAX_REPLICA_CHANGES_SIZE = MAX_REPLICA_CHANGES_SIZE
    REPLICA_MULTIPLE_TIMEOUT = REPLICA_MULTIPLE_TIMEOUT

    def __init__(self, request):
        self.request = request
        self.xom = request.registry["xom"]

    @contextlib.contextmanager
    def update_replica_status(self, serial, streaming=False):
        headers = self.request.headers
        uuid = headers.get(H_REPLICA_UUID)
        if uuid:
            polling_replicas = self.xom.polling_replicas
            polling_replicas[uuid] = {
                "remote-ip": self.request.get_remote_ip(),
                # the replica always polls its own serial+1
                # and we want to show where the replica serial is at
                "serial": int(serial) - 1,
                "in-request": True,
                "is-streaming": streaming,
                "last-request": time.time(),
                "outside-url": headers.get(H_REPLICA_OUTSIDE_URL),
            }
            try:
                yield
            finally:
                polling_replicas[uuid]["last-request"] = time.time()
                polling_replicas[uuid]["in-request"] = streaming
        else:  # just a regular request
            yield

    def verify_primary(self):
        if not self.xom.is_primary():
            raise HTTPForbidden("Replication protocol disabled")
        expected_uuid = self.request.headers.get(
            H_EXPECTED_PRIMARY_ID,
            self.request.headers.get(H_EXPECTED_MASTER_ID))
        primary_uuid = self.xom.config.get_primary_uuid()
        # we require the header but it is allowed to be empty
        # (during initialization)
        if expected_uuid is None:
            msg = f"replica sent no {H_EXPECTED_PRIMARY_ID} or {H_EXPECTED_MASTER_ID} header"
            threadlog.error(msg)
            raise HTTPBadRequest(msg)

        if expected_uuid and expected_uuid != primary_uuid:
            threadlog.error(
                "expected %r as primary_uuid, replica sent %r",
                primary_uuid, expected_uuid)
            raise HTTPBadRequest(
                "expected %s as primary_uuid, replica sent %s" %
                (primary_uuid, expected_uuid))

        identity = self.request.identity
        if identity is not None and not isinstance(identity, ReplicaIdentity):
            raise HTTPForbidden(
                "Authenticated identity '%r' isn't from replica." % identity)

    @view_config(route_name="/+changelog/{serial}")
    def get_changes(self):
        # this method is called from all replica servers
        # and either returns changelog entry content for {serial} or,
        # if it points to the "next" serial, will block and wait
        # until that serial is committed.  However, after
        # MAX_REPLICA_BLOCK_TIME, we return 202 Accepted to indicate
        # the replica should try again.  The latter has two benefits:
        # - nginx' timeout would otherwise return 504 (Gateway Timeout)
        # - if the replica is not waiting anymore we would otherwise
        #   never time out here, leading to more and more threads
        # if no commits happen.

        self.verify_primary()

        serial = int(self.request.matchdict["serial"])

        with self.update_replica_status(serial):
            keyfs = self.xom.keyfs
            self._wait_for_serial(serial)

            raw_entry = keyfs.tx.conn.get_raw_changelog_entry(serial)

            devpi_serial = keyfs.get_current_serial()
            return Response(body=raw_entry, status=200, headers={
                "Content-Type": "application/octet-stream",
                "X-DEVPI-SERIAL": str(devpi_serial)})

    @view_config(route_name="/+changelog/{serial}-")
    def get_multiple_changes(self):
        acceptable = self.request.accept.acceptable_offers(
            [REPLICA_CONTENT_TYPE, "application/octet-stream"])
        preferres_streaming = (
            (REPLICA_CONTENT_TYPE, 1.0) in acceptable
            and ("application/octet-stream", 1.0) not in acceptable)
        if preferres_streaming:
            # a replica which accepts streams has a lower priority for
            # "application/octet-stream" as the old default "Accept: */*"
            return self.get_streaming_changes()

        self.verify_primary()

        start_serial = int(self.request.matchdict["serial"])

        with self.update_replica_status(start_serial):
            keyfs = self.xom.keyfs
            self._wait_for_serial(start_serial)
            devpi_serial = keyfs.get_current_serial()
            all_changes = []
            raw_size = 0
            start_time = time.time()
            for serial in range(start_serial, devpi_serial + 1):
                raw_entry = keyfs.tx.conn.get_raw_changelog_entry(serial)
                raw_size += len(raw_entry)
                (changes, rel_renames) = loads(raw_entry)
                all_changes.append((serial, changes))
                now = time.time()
                if raw_size > self.MAX_REPLICA_CHANGES_SIZE:
                    threadlog.debug('Changelog raw size %s', raw_size)
                    break
                if (now - start_time) > (self.REPLICA_MULTIPLE_TIMEOUT):
                    threadlog.debug('Changelog timeout %s', raw_size)
                    break
            raw_entry = dumps(all_changes)
            return Response(body=raw_entry, status=200, headers={
                "Content-Type": "application/octet-stream",
                "X-DEVPI-SERIAL": str(devpi_serial)})

    def get_streaming_changes(self):
        self.verify_primary()

        start_serial = int(self.request.matchdict["serial"])

        keyfs = self.xom.keyfs
        self._wait_for_serial(start_serial)
        devpi_serial = keyfs.get_current_serial()
        threadlog.info("Streaming from %s to %s", start_serial, devpi_serial)

        def iter_changelog_entries():
            for serial in range(start_serial, devpi_serial + 1):
                with keyfs.get_connection() as conn:
                    raw = conn.get_raw_changelog_entry(serial)
                with self.update_replica_status(serial, streaming=True):
                    yield dumps(serial)
                    yield raw
            # update status again when done
            with self.update_replica_status(devpi_serial + 1, streaming=False):
                pass

        return Response(
            app_iter=buffered_iterator(iter_changelog_entries()),
            status=200, headers={
                "Content-Type": REPLICA_CONTENT_TYPE,
                "X-DEVPI-SERIAL": str(devpi_serial)})

    def _wait_for_serial(self, serial):
        keyfs = self.xom.keyfs
        next_serial = keyfs.get_next_serial()
        if serial > next_serial:
            raise HTTPNotFound("can only wait for next serial")
        elif serial == next_serial:
            if 'initial_fetch' in self.request.params:
                timeout = 1
            else:
                timeout = self.MAX_REPLICA_BLOCK_TIME
            arrived = keyfs.wait_tx_serial(serial, timeout=timeout)
            if not arrived:
                raise HTTPAccepted(
                    "no new transaction yet",
                    headers={"X-DEVPI-SERIAL": str(keyfs.get_current_serial())})
        return serial


class ReplicaThread:
    H_REPLICA_FILEREPL = H_REPLICA_FILEREPL
    H_REPLICA_UUID = H_REPLICA_UUID
    REPLICA_REQUEST_TIMEOUT = REPLICA_REQUEST_TIMEOUT
    ERROR_SLEEP = 50

    def __init__(self, xom):
        self.xom = xom
        self.shared_data = FileReplicationSharedData(xom)
        keyfs = self.xom.keyfs
        keyfs.subscribe_on_import(self.shared_data.on_import)
        self.file_replication_threads = []
        num_threads = xom.config.file_replication_threads
        self.shared_data.num_threads = num_threads
        threadlog.info("Using %s file download threads.", num_threads)
        for i in range(num_threads):
            frt = FileReplicationThread(xom, self.shared_data)
            self.file_replication_threads.append(frt)
            xom.thread_pool.register(frt)
        self.initial_queue_thread = InitialQueueThread(xom, self.shared_data)
        xom.thread_pool.register(self.initial_queue_thread)
        self.primary_auth = xom.config.primary_auth
        self.primary_url = xom.config.primary_url
        self.use_streaming = xom.config.replica_streaming
        self._primary_serial = None
        self._primary_serial_timestamp = None
        self.started_at = None
        # updated whenever we try to connect to the primary
        self.primary_contacted_at = None
        # updated on valid reply or 202 from primary
        self.update_from_primary_at = None
        # set whenever the primary serial and current replication serial match
        self.replica_in_sync_at = None
        self.session = self.xom.new_http_session("replica")
        self.initial_fetch = True

    @cached_property
    def auth_serializer(self):
        return get_auth_serializer(self.xom.config)

    def get_master_serial(self):
        warnings.warn(
            "get_master_serial is deprecated, use get_primary_serial instead",
            DeprecationWarning,
            stacklevel=2)
        return self.get_primary_serial()

    def get_master_serial_timestamp(self):
        warnings.warn(
            "get_master_serial_timestamp is deprecated, use get_primary_serial_timestamp instead",
            DeprecationWarning,
            stacklevel=2)
        return self.get_primary_serial_timestamp()

    @property
    def _master_serial(self):
        warnings.warn(
            "_master_serial is deprecated, use _primary_serial instead",
            DeprecationWarning,
            stacklevel=2)
        return self._primary_serial

    @property
    def _master_serial_timestamp(self):
        warnings.warn(
            "_master_serial_timestamp is deprecated, use _primary_serial_timestamp instead",
            DeprecationWarning,
            stacklevel=2)
        return self._primary_serial_timestamp

    @property
    def master_auth(self):
        warnings.warn(
            "master_auth is deprecated, use primary_auth instead",
            DeprecationWarning,
            stacklevel=2)
        return self.primary_auth

    @property
    def master_contacted_at(self):
        warnings.warn(
            "master_contacted_at is deprecated, use primary_contacted_at instead",
            DeprecationWarning,
            stacklevel=2)
        return self.primary_contacted_at

    @property
    def master_url(self):
        warnings.warn(
            "master_url is deprecated, use primary_url instead",
            DeprecationWarning,
            stacklevel=2)
        return self.primary_url

    @property
    def update_from_master_at(self):
        warnings.warn(
            "update_from_master_at is deprecated, use update_from_primary_at instead",
            DeprecationWarning,
            stacklevel=2)
        return self.update_from_primary_at

    def get_primary_serial(self):
        return self._primary_serial

    def get_primary_serial_timestamp(self):
        return self._primary_serial_timestamp

    def update_primary_serial(self, serial, *, update_sync=True, ignore_lower=False):
        now = time.time()
        # record that we got a reply from the primary, so we can produce status
        # information about the connection to primary
        self.update_from_primary_at = now
        if update_sync and self.xom.keyfs.get_current_serial() == serial:
            with self.shared_data._replica_in_sync_cv:
                self.replica_in_sync_at = now
                self.shared_data._replica_in_sync_cv.notify_all()
        if self._primary_serial is not None and serial <= self._primary_serial:
            if serial < self._primary_serial and not ignore_lower:
                self.log.error(
                    "Got serial %s from primary which is smaller than last "
                    "recorded serial %s.", serial, self._primary_serial)
            return
        self._primary_serial = serial
        self._primary_serial_timestamp = now

    def fetch(self, handler, url):
        if self.initial_fetch:
            url = URL(url)
            if url.query:
                url = url.replace(query=url.query + '&initial_fetch')
            else:
                url = url.replace(query='initial_fetch')
            url = url.url
        log = self.log
        config = self.xom.config
        log.info("fetching %s", url)
        uuid, primary_uuid = make_uuid_headers(config.nodeinfo)
        assert uuid != primary_uuid
        try:
            self.primary_contacted_at = time.time()
            token = self.auth_serializer.dumps(uuid)
            headers = {
                H_REPLICA_UUID: uuid,
                H_EXPECTED_MASTER_ID: primary_uuid,
                H_EXPECTED_PRIMARY_ID: primary_uuid,
                H_REPLICA_OUTSIDE_URL: config.args.outside_url,
                'Authorization': 'Bearer %s' % token}
            if self.use_streaming:
                headers["Accept"] = REPLICA_ACCEPT_STREAMING
            r = self.session.get(
                url,
                allow_redirects=False,
                auth=self.primary_auth,
                headers=headers,
                stream=self.use_streaming,
                timeout=self.REPLICA_REQUEST_TIMEOUT)
        except Exception as e:
            msg = ''.join(traceback.format_exception_only(e.__class__, e)).strip()
            log.error("error fetching %s: %s", url, msg)  # noqa: TRY400
            return False

        with contextlib.closing(r):
            if r.status_code in (301, 302):
                log.error(
                    "%s %s: redirect detected at %s to %s",
                    r.status_code, r.reason, url, r.headers.get('Location'))
                return False

            if r.status_code not in (200, 202):
                log.error("%s %s: failed fetching %s", r.status_code, r.reason, url)
                return False

            # we check that the remote instance
            # has the same UUID we saw last time
            primary_uuid = config.get_primary_uuid()
            remote_primary_uuid = r.headers.get(
                H_PRIMARY_UUID,
                r.headers.get(H_MASTER_UUID))
            if H_MASTER_UUID in r.headers and r.headers.get(H_MASTER_UUID, remote_primary_uuid) != remote_primary_uuid:
                log.error(
                    "remote has differing values for %r and %r headers: %s",
                    H_PRIMARY_UUID, H_MASTER_UUID, r.headers)
                self.thread.sleep(self.ERROR_SLEEP)
                return True
            if not remote_primary_uuid:
                # we don't fatally leave the process because
                # it might just be a temporary misconfiguration
                # for example of a nginx frontend
                log.error("remote provides no %r or %r header, running "
                          "<devpi-server-2.1?"
                          " headers were: %s",
                          H_PRIMARY_UUID, H_MASTER_UUID, r.headers)
                self.thread.sleep(self.ERROR_SLEEP)
                return True
            if primary_uuid and remote_primary_uuid != primary_uuid:
                # we got a primary_uuid and it is not the one we
                # expect, we are replicating for -- it's unlikely this heals
                # itself.  It's thus better to die and signal we can't operate.
                log.error("FATAL: primary UUID %r does not match "
                          "expected primary UUID %r. EXITING.",
                          remote_primary_uuid, primary_uuid)
                # force exit of the process
                os._exit(3)

            try:
                remote_serial = int(r.headers["X-DEVPI-SERIAL"])
            except Exception as e:
                msg = ''.join(traceback.format_exception_only(e.__class__, e)).strip()
                log.error("error fetching %s: %s", url, msg)  # noqa: TRY400
                return False

            if r.status_code == 200:
                # we successfully received data so let's
                # record the primary_uuid for future consistency checks
                if not primary_uuid:
                    self.xom.config.set_primary_uuid(remote_primary_uuid)
                # also record the current primary serial for status info
                self.update_primary_serial(remote_serial)
                try:
                    handler(r)
                except mythread.Shutdown:
                    raise
                except Exception:
                    log.exception("could not process: %s", r.url)
                else:
                    # we successfully received data so let's
                    # record the primary_uuid for future consistency checks
                    if not primary_uuid:
                        self.xom.config.set_primary_uuid(remote_primary_uuid)
                    # also record the current primary serial for status info
                    self.update_primary_serial(remote_serial, ignore_lower=True)
                    return True
            elif r.status_code == 202:
                remote_serial = int(r.headers["X-DEVPI-SERIAL"])
                log.debug("%s: trying again %s\n", r.status_code, url)
                # also record the current primary serial for status info
                self.update_primary_serial(remote_serial)
                return True
            return False

    def handler_single(self, response, serial):
        changes, rel_renames = loads(response.content)
        self.xom.keyfs.import_changes(serial, changes)

    def fetch_single(self, serial):
        url = self.primary_url.joinpath("+changelog", str(serial)).url
        return self.fetch(
            partial(self.handler_single, serial=serial),
            url)

    def handler_multi(self, response):
        if response.headers["content-type"] == REPLICA_CONTENT_TYPE:
            with contextlib.closing(response):
                readableiterable = ReadableIterabel(
                    response.iter_content(chunk_size=None))
                stream = io.BufferedReader(readableiterable, buffer_size=65536)
                try:
                    while True:
                        serial = load(stream)
                        (changes, rel_renames) = load(stream)
                        self.xom.keyfs.import_changes(serial, changes)
                        self.update_primary_serial(serial, update_sync=False, ignore_lower=True)
                except StopIteration:
                    pass
                except EOFError:
                    pass
        else:
            all_changes = loads(response.content)
            for serial, changes in all_changes:
                self.xom.keyfs.import_changes(serial, changes)
                self.update_primary_serial(serial, update_sync=False, ignore_lower=True)

    def fetch_multi(self, serial):
        url = self.primary_url.joinpath("+changelog", "%s-" % serial).url
        return self.fetch(self.handler_multi, url)

    def tick(self):
        self.thread.exit_if_shutdown()
        serial = self.xom.keyfs.get_next_serial()
        result = self.fetch_multi(serial)
        if not result:
            serial = self.xom.keyfs.get_next_serial()
            # BBB remove with 6.0.0
            result = self.fetch_single(serial)
        if not result:
            # we got an error, let's wait a bit
            self.thread.sleep(5.0)
        else:
            # from now on we do polling
            self.initial_fetch = False

    def thread_run(self):
        # within a devpi replica server this thread is the only writer
        self.started_at = time.time()
        self.log = thread_push_log("[REP]")
        last_time = time.time()
        while 1:
            try:
                self.tick()
                if time.time() - last_time > 10:
                    last_time = time.time()
                    qsize = self.shared_data.queue.qsize()
                    if qsize:
                        threadlog.info("File download queue size ~ %s", qsize)
            except mythread.Shutdown:
                raise
            except BaseException:
                self.log.exception(
                    "Unhandled exception in replica thread.")
                self.thread.sleep(1.0)

    def thread_shutdown(self):
        self.session.close()

    def wait(self, error_queue=False):
        self.shared_data.wait(error_queue=error_queue)


def register_key_subscribers(xom):
    xom.keyfs.PROJSIMPLELINKS.on_key_change(SimpleLinksChanged(xom))


class FileReplicationSharedData(object):
    QUEUE_TIMEOUT = 1
    ERROR_QUEUE_DELAY_MULTIPLIER = 1.5
    ERROR_QUEUE_REPORT_DELAY = 2 * 60
    ERROR_QUEUE_MAX_DELAY = 60 * 60

    def __init__(self, xom):
        from queue import Empty, PriorityQueue
        self.Empty = Empty
        self.xom = xom
        self.queue = PriorityQueue()
        self.error_queue = PriorityQueue()
        self.deleted = LRUCache(100)
        self.index_types = LRUCache(1000)
        self.errors = ReplicationErrors()
        self._replica_in_sync_cv = threading.Condition()
        self.last_added = None
        self.last_errored = None
        self.last_processed = None

    def on_import(self, serial, changes):
        keyfs = self.xom.keyfs
        user_keyname = keyfs.USER.name
        for key in changes:
            if key.name == user_keyname:
                self.update_index_types(keyfs, serial, key, *changes[key])
        file_keynames = frozenset(
            (keyfs.STAGEFILE.name, keyfs.PYPIFILE_NOMD5.name))
        for key in changes:
            if key.name in file_keynames:
                self.on_import_file(keyfs, serial, key, *changes[key])

    def on_import_file(self, keyfs, serial, key, val, back_serial):
        try:
            index_type = self.get_index_type_for(key)
        except KeyError:
            stage = self.xom.model.getstage(
                key.params['user'], key.params['index'])
            if stage is None:
                # deleted stage
                stagename = f"{key.params['user']}/{key.params['index']}"
                self.set_index_type_for(stagename, None)
            else:
                self.set_index_type_for(stage.name, stage.ixconfig['type'])
            index_type = self.get_index_type_for(key)
        if self.xom.replica_thread.replica_in_sync_at is None:
            # Don't queue files from mirrors until we have been in sync first.
            # The InitialQueueThread will queue in one go on initial sync
            if index_type == IndexType("mirror"):
                return
            # Don't queue from deleted indexes
            if index_type == IndexType(None):
                return
            # let the queue be processed before filling it further
            if self.queue.qsize() > 50000:
                return

        # note the negated serial for the PriorityQueue
        self.queue.put((
            index_type, -serial, key.relpath, key.name, val, back_serial))
        self.last_added = time.time()

    def update_index_types(self, keyfs, serial, key, val, back_serial):
        if val is None:
            val = {}
        current_index_types = {
            name: config["type"]
            for name, config in val.get("indexes", {}).items()}
        val = {}
        if back_serial >= 0:
            try:
                val = keyfs.tx.get_value_at(key, back_serial)
            except KeyError:
                pass
        old_index_types = {
            name: config["type"]
            for name, config in val.get("indexes", {}).items()}
        username = key.params["user"]
        removed_indexes = set(old_index_types).difference(current_index_types)
        for indexname in removed_indexes:
            self.set_index_type_for(
                f"{username}/{indexname}", None)
        for indexname, indextype in current_index_types.items():
            self.set_index_type_for(
                f"{username}/{indexname}", indextype)

    def next_ts(self, delay):
        return time.time() + delay

    def add_errored(self, index_type, serial, key, keyname, value, back_serial, ts=None, delay=11):
        if ts is None:
            ts = self.next_ts(min(delay, self.ERROR_QUEUE_MAX_DELAY))
        # this priority queue is ordered by time stamp
        self.error_queue.put(
            (ts, delay, index_type, serial, key, keyname, value, back_serial))
        self.last_errored = time.time()

    def get_index_type_for(self, key, default=notset):
        index_name = "%s/%s" % (key.params['user'], key.params['index'])
        result = self.index_types.get(index_name, notset)
        if result is notset:
            if default is notset:
                raise KeyError
            return IndexType(default)
        return result

    def set_index_type_for(self, stagename, index_type):
        self.index_types.put(stagename, IndexType(index_type))

    def is_in_future(self, ts):
        return ts > time.time()

    def process_next_errored(self, handler):
        try:
            # it seems like without the timeout this isn't triggered frequent
            # enough, the thread was waiting a long time even though there
            # were already/still items in the queue
            info = self.error_queue.get(timeout=self.QUEUE_TIMEOUT)
        except self.Empty:
            return
        (ts, delay, index_type, serial, key, keyname, value, back_serial) = info
        try:
            if self.is_in_future(ts):
                # not current yet, so re-add it
                self.add_errored(
                    index_type, serial, key, keyname, value, back_serial,
                    ts=ts, delay=delay)
                return
            handler(index_type, serial, key, keyname, value, back_serial)
        except Exception:
            # another failure, re-add with longer delay
            self.add_errored(
                index_type, serial, key, keyname, value, back_serial,
                delay=delay * self.ERROR_QUEUE_DELAY_MULTIPLIER)
            if delay > self.ERROR_QUEUE_REPORT_DELAY:
                threadlog.exception(
                    "There repeatedly has been an error during file download.")
        finally:
            self.error_queue.task_done()
            self.last_processed = time.time()

    def process_next(self, handler):
        try:
            # it seems like without the timeout this isn't triggered frequent
            # enough, the thread was waiting a long time even though there
            # were already/still items in the queue
            info = self.queue.get(timeout=self.QUEUE_TIMEOUT)
        except self.Empty:
            # when the regular queue is empty, we retry previously errored ones
            return self.process_next_errored(handler)
        (index_type, serial, key, keyname, value, back_serial) = info
        # negate again, because it was negated for the PriorityQueue
        serial = -serial
        try:
            handler(index_type, serial, key, keyname, value, back_serial)
        except Exception as e:
            threadlog.warn(
                "Error during file replication for %s: %s",
                key, lazy_format_exception(e))
            self.add_errored(index_type, serial, key, keyname, value, back_serial)
        finally:
            self.queue.task_done()
            self.last_processed = time.time()

    def wait(self, error_queue=False):
        self.queue.join()
        if error_queue:
            self.error_queue.join()


@hookimpl
def devpiserver_metrics(request):
    result = []
    xom = request.registry["xom"]
    replica_thread = getattr(xom, 'replica_thread', None)
    if not isinstance(replica_thread, ReplicaThread):
        return result
    shared_data = getattr(replica_thread, 'shared_data', None)
    if not isinstance(shared_data, FileReplicationSharedData):
        return result
    deleted_cache = shared_data.deleted
    indextypes_cache = shared_data.index_types
    result.extend([
        ('devpi_server_replica_file_download_queue_size', 'gauge', shared_data.queue.qsize()),
        ('devpi_server_replica_file_download_error_queue_size', 'gauge', shared_data.error_queue.qsize()),
        ('devpi_server_replica_deleted_cache_evictions', 'counter', deleted_cache.evictions),
        ('devpi_server_replica_deleted_cache_hits', 'counter', deleted_cache.hits),
        ('devpi_server_replica_deleted_cache_lookups', 'counter', deleted_cache.lookups),
        ('devpi_server_replica_deleted_cache_misses', 'counter', deleted_cache.misses),
        ('devpi_server_replica_deleted_cache_size', 'gauge', deleted_cache.size),
        ('devpi_server_replica_deleted_cache_items', 'gauge', len(deleted_cache.data) if deleted_cache.data else 0),
        ('devpi_server_replica_indextypes_cache_evictions', 'counter', indextypes_cache.evictions),
        ('devpi_server_replica_indextypes_cache_hits', 'counter', indextypes_cache.hits),
        ('devpi_server_replica_indextypes_cache_lookups', 'counter', indextypes_cache.lookups),
        ('devpi_server_replica_indextypes_cache_misses', 'counter', indextypes_cache.misses),
        ('devpi_server_replica_indextypes_cache_size', 'gauge', indextypes_cache.size),
        ('devpi_server_replica_indextypes_cache_items', 'gauge', len(indextypes_cache.data) if indextypes_cache.data else 0)])
    return result


def includeme(config):
    config.add_route("/+changelog/{serial}", r"/+changelog/{serial:\d+}")
    config.add_route("/+changelog/{serial}-", r"/+changelog/{serial:\d+}-")
    config.scan("devpi_server.replica")


@hookimpl
def devpiserver_pyramid_configure(config, pyramid_config):
    # by using include, the package name doesn't need to be set explicitly
    # for registrations of static views etc
    pyramid_config.include("devpi_server.replica")


@devpiweb_hookimpl
def devpiweb_get_status_info(request):
    xom = request.registry['xom']
    replica_thread = getattr(xom, 'replica_thread', None)
    shared_data = getattr(replica_thread, 'shared_data', None)
    msgs = []
    if isinstance(shared_data, FileReplicationSharedData):
        now = time.time()
        qsize = shared_data.queue.qsize()
        if qsize:
            last_activity_seconds = 0
            if shared_data.last_processed is None and shared_data.last_added:
                last_activity_seconds = (now - shared_data.last_added)
            elif shared_data.last_processed:
                last_activity_seconds = (now - shared_data.last_processed)
            if last_activity_seconds > 300:
                msgs.append(dict(status="fatal", msg="No files downloaded for more than 5 minutes"))
            elif last_activity_seconds > 60:
                msgs.append(dict(status="warn", msg="No files downloaded for more than 1 minute"))
            if qsize > 10:
                msgs.append(dict(status="warn", msg="%s items in file download queue" % qsize))
        error_qsize = shared_data.error_queue.qsize()
        if error_qsize:
            msgs.append(dict(status="warn", msg="Errors during file downloads, %s files queued for retry" % error_qsize))
    return msgs


class FileReplicationThread:
    def __init__(self, xom, shared_data):
        self.xom = xom
        self.shared_data = shared_data
        self.session = self.xom.new_http_session("replica")
        self.file_search_path = None
        if self.xom.config.replica_file_search_path is not None:
            search_path = os.path.join(
                self.xom.config.replica_file_search_path, '+files')
            if os.path.isdir(search_path):
                self.file_search_path = search_path
            else:
                self.file_search_path = self.xom.config.replica_file_search_path
            if not os.path.isdir(self.file_search_path):
                fatal(
                    "path for existing files doesn't exist: %s",
                    self.xom.config.replica_file_search_path)
        self.use_hard_links = self.xom.config.hard_links
        self.uuid, primary_uuid = make_uuid_headers(xom.config.nodeinfo)
        assert self.uuid != primary_uuid

    @cached_property
    def auth_serializer(self):
        return get_auth_serializer(self.xom.config)

    def find_pre_existing_file(self, entry):
        if self.file_search_path is None:
            return (None, None)
        path = os.path.join(self.file_search_path, entry.relpath)
        if not os.path.exists(path):
            # look for file in export layout
            parts = (
                entry.user, entry.index,
                entry.project, entry.version,
                entry.basename)
            if all(part is not None for part in parts):
                path = os.path.join(self.file_search_path, *parts)
        if not os.path.exists(path):
            threadlog.debug("path for existing file not found: %s", path)
            return (None, None)
        threadlog.debug("checking existing file: %s", path)
        f = open(path, "rb")  # noqa: SIM115 - file is returned
        errors = entry.hashes.errors_for(f)
        if errors:
            f.close()
            # get one error
            error_msg = errors.get(
                entry.best_available_hash_type, next(iter(errors)))['msg']
            threadlog.info(
                "%s: %s", error_msg, path)
            return (None, None)
        threadlog.info("using matching existing file: %s", path)
        f.seek(0)
        if self.use_hard_links:
            f.devpi_srcpath = path
        return (f, entry.hashes)

    def importer(self, serial, key, val, back_serial, session):
        threadlog.debug("FileReplicationThread.importer for %s, %s", key, val)
        keyfs = self.xom.keyfs
        relpath = key.relpath
        entry = self.xom.filestore.get_file_entry_from_key(key, meta=val)
        if val is None:
            if back_serial >= 0:
                with keyfs.filestore_transaction():
                    # file was deleted, still might never have been replicated
                    if entry.file_exists():
                        threadlog.info("mark for deletion: %s", relpath)
                        entry.file_delete()
                self.shared_data.errors.remove(entry)
                return
        if entry.last_modified is None:
            # there is no remote file
            self.shared_data.errors.remove(entry)
            return
        with keyfs.filestore_transaction():
            if entry.file_exists():
                # we already have a file
                self.shared_data.errors.remove(entry)
                return

        (f, hashes) = self.find_pre_existing_file(entry)
        if f is not None:
            # we found a matching existing file
            with keyfs.filestore_transaction():
                entry.file_set_content_no_meta(f, hashes=hashes)
                # on Windows we need to close the file
                # before the transaction closes
                f.close()
            self.shared_data.errors.remove(entry)
            return
        del f, hashes

        threadlog.info(
            "retrieving file from primary for serial %s: %s", serial, relpath)
        url = self.xom.config.primary_url.joinpath(relpath).url
        # we perform the request with a special header so that
        # the primary can avoid getting "volatile" links
        token = self.auth_serializer.dumps(self.uuid)
        r = session.get(
            url, allow_redirects=False,
            headers={
                H_REPLICA_FILEREPL: "YES",
                H_REPLICA_UUID: self.uuid,
                'Authorization': 'Bearer %s' % token},
            stream=True,
            timeout=self.xom.config.args.request_timeout)
        if r.status_code == 302:
            r.close()
            # mirrors might redirect to external file when
            # mirror_use_external_urls is set
            threadlog.info(
                "ignoring because of redirection to external URL: %s",
                relpath)
            self.shared_data.errors.remove(entry)
            return
        if r.status_code == 410:
            # primary indicates Gone for files which were later deleted
            r.close()
            threadlog.info(
                "ignoring because of later deletion: %s",
                relpath)
            self.shared_data.errors.remove(entry)
            return

        if r.status_code in (404, 502):
            r.close()
            stagename = '/'.join(relpath.split('/')[:2])
            with self.xom.keyfs.read_transaction(at_serial=serial):
                stage = self.xom.model.getstage(stagename)
            if stage.ixconfig['type'] == 'mirror':
                threadlog.warn(
                    "ignoring file which couldn't be retrieved from mirror index '%s': %s",
                    stagename, relpath)
                self.shared_data.errors.remove(entry)
                return

        if r.status_code != 200:
            r.close()
            threadlog.error(
                "error downloading '%s' from primary, will be retried later: %s",
                relpath, r.reason)
            # add the error for the UI
            self.shared_data.errors.add(dict(
                url=r.url,
                message=r.reason,
                relpath=entry.relpath))
            # and raise for retrying later
            raise FileReplicationError(r, relpath)

        with contextlib.ExitStack() as cstack:
            cstack.callback(r.close)

            with keyfs.filestore_transaction():
                # get a new file, but close the transaction again
                f = cstack.enter_context(entry.file_new_open())

            file_streamer = FileStreamer(f, entry, r)

            try:
                for _chunk in file_streamer:
                    # we only need the data to be written to the file
                    pass
            except Exception as err:
                if isinstance(err, ChecksumError):
                    threadlog.error(
                        "checksum mismatch for '%s', will be retried later: %s",
                        relpath, r.reason)
                self.shared_data.errors.add(dict(
                    url=r.url,
                    message=str(err),
                    relpath=entry.relpath))
                return

            # in case there were errors before, we can now remove them
            self.shared_data.errors.remove(entry)
            with keyfs.filestore_transaction():
                entry.file_set_content_no_meta(f, hashes=file_streamer.hashes)
                # on Windows we need to close the file
                # before the transaction closes
                f.close()

    def handler(self, index_type, serial, key, keyname, value, back_serial):
        keyfs = self.xom.keyfs
        if value is None:
            self.shared_data.deleted.put(key, serial)
        else:
            deleted_serial = self.shared_data.deleted.get(key)
            if deleted_serial is not None:
                if serial <= deleted_serial:
                    return
                else:
                    self.shared_data.deleted.invalidate(key)
        typedkey = keyfs.get_key_instance(keyname, key)
        self.importer(
            serial, typedkey, value, back_serial, self.session)
        entry = self.xom.filestore.get_file_entry_from_key(typedkey, meta=value)
        if not entry.project or not entry.version:
            return
        # run hook
        with keyfs.read_transaction(at_serial=serial):
            stage = self.xom.model.getstage(entry.user, entry.index)
            if stage is None:
                return
            stage.offline = True
            name = normalize_name(entry.project)
            try:
                linkstore = stage.get_linkstore_perstage(name, entry.version)
            except (stage.MissesRegistration, stage.UpstreamError):
                if index_type == IndexType(None) or index_type == IndexType("mirror"):
                    return
                raise
            links = linkstore.get_links(basename=entry.basename)
            for link in links:
                self.xom.config.hook.devpiserver_on_replicated_file(
                    stage=stage, project=name, version=entry.version, link=link,
                    serial=serial, back_serial=back_serial,
                    is_from_mirror=index_type == IndexType("mirror"))

    def tick(self):
        self.thread.exit_if_shutdown()
        self.shared_data.process_next(self.handler)

    def thread_run(self):
        thread_push_log("[FREP]")
        while 1:
            try:
                self.tick()
            except mythread.Shutdown:
                raise
            except Exception:
                threadlog.exception(
                    "Unhandled exception in file replication thread.")
                self.thread.sleep(1.0)


class InitialQueueThread(object):
    def __init__(self, xom, shared_data):
        self.xom = xom
        self.shared_data = shared_data

    def thread_run(self):
        thread_push_log("[FREPQ]")
        keyfs = self.xom.keyfs
        threadlog.info("Queuing files for possible download from primary")
        keys = (keyfs.get_key('PYPIFILE_NOMD5'), keyfs.get_key('STAGEFILE'))
        last_time = time.time()
        processed = 0
        queued = 0
        # wait until we are in sync for the first time
        with self.shared_data._replica_in_sync_cv:
            self.shared_data._replica_in_sync_cv.wait()
        with keyfs.read_transaction() as tx:
            for user in self.xom.model.get_userlist():
                for stage in user.getstages():
                    self.shared_data.set_index_type_for(
                        stage.name, stage.ixconfig['type'])
            relpaths = tx.iter_relpaths_at(keys, tx.at_serial)
            for item in relpaths:
                self.thread.exit_if_shutdown()
                if item.value is None:
                    continue
                if self.shared_data.queue.qsize() > self.shared_data.num_threads:
                    # let the queue be processed before filling it further
                    self.shared_data.wait()
                if time.time() - last_time > 5:
                    last_time = time.time()
                    threadlog.info(
                        "Processed a total of %s files (serial %s/%s) and queued %s so far.",
                        processed, tx.at_serial - item.serial, tx.at_serial, queued)
                processed = processed + 1
                key = keyfs.get_key_instance(item.keyname, item.relpath)
                entry = FileEntry(key, item.value)
                if entry.file_exists() or not entry.last_modified:
                    continue
                index_type = self.shared_data.get_index_type_for(key, None)
                # note the negated serial for the PriorityQueue
                # the index_type boolean will prioritize non mirrors
                self.shared_data.queue.put((
                    index_type, -item.serial, item.relpath,
                    item.keyname, item.value, item.back_serial))
                queued = queued + 1
        threadlog.info(
            "Queued %s of %s files for possible download from primary",
            queued, processed)


class SimpleLinksChanged:
    """ Event executed in notification thread based on a pypi link change.
    It allows a replica to sync up the local full projectnames list."""
    def __init__(self, xom):
        self.xom = xom

    def __call__(self, ev):
        threadlog.debug("SimpleLinksChanged %s", ev.typedkey)
        cache = ev.value
        # get the normalized project (PYPILINKS uses it)
        username = ev.typedkey.params["user"]
        index = ev.typedkey.params["index"]
        project = ev.typedkey.params["project"]
        if not project:
            threadlog.error("project %r missing", project)
            return
        assert normalize_name(project) == project

        with self.xom.keyfs.read_transaction():
            mirror_stage = self.xom.model.getstage(username, index)
            if mirror_stage and mirror_stage.ixconfig["type"] == "mirror":
                cache_projectnames = mirror_stage.cache_projectnames
                if cache is None:  # deleted
                    cache_projectnames.discard(project)
                else:
                    cache_projectnames.add(project)


hop_by_hop = frozenset((
    'connection',
    'keep-alive',
    'proxy-authenticate',
    'proxy-authorization',
    'te',
    'trailers',
    'transfer-encoding',
    'upgrade'
))


def clean_request_headers(request):
    result = EnvironHeaders({})
    result.update(request.headers)
    result.pop('host', None)
    return result


def clean_response_headers(response):
    headers = ResponseHeaders()
    # remove hop by hop headers, see:
    # https://www.mnot.net/blog/2011/07/11/what_proxies_must_do
    hop_keys = set(hop_by_hop)
    connection = response.headers.get('connection')
    if connection and connection.lower() != 'close':
        hop_keys.update(x.strip().lower() for x in connection.split(','))
    for k, v in response.headers.items():
        if k.lower() in hop_keys:
            continue
        headers[k] = v
    return headers


class BodyFileWrapper:
    # required to provide length to prevent transfer-encoding: chunked

    def __init__(self, bf, length):
        self.read = bf.read
        self.len = length


def proxy_request_to_primary(xom, request, *, stream=False):
    primary_url = xom.config.primary_url
    request_url = URL(request.url)
    url = (
        primary_url
        .joinpath(request_url.path)
        .replace(query=request_url.query)
        .url)
    assert url.startswith(primary_url.url)
    http = xom._httpsession
    with threadlog.around("info", "relaying: %s %s", request.method, url):
        try:
            headers = clean_request_headers(request)
            length = None
            with suppress(ValueError, TypeError):
                length = int(headers.get('Content-Length'))
            if length:
                body = BodyFileWrapper(request.body_file, length)
            else:
                body = request.body
            return http.request(request.method, url,
                                data=body,
                                headers=headers,
                                stream=stream,
                                allow_redirects=False,
                                timeout=xom.config.args.proxy_timeout)
        except http.Errors as e:
            msg = f"proxy-write-to-primary {url}: {e}"
            raise UpstreamError(msg) from e


def proxy_write_to_primary(xom, request):
    """ relay modifying http requests to primary and wait until
    the change is replicated back.
    """
    r = proxy_request_to_primary(xom, request, stream=True)
    # for redirects, the body is already read and stored in the ``next``
    # attribute (see requests.sessions.send)
    if r.raw.closed and r.next:
        def app_iter():
            with contextlib.closing(r):
                yield r.next.body
    else:
        def app_iter():
            with contextlib.closing(r):
                yield from r.raw.stream()
    if r.status_code < 400:
        commit_serial = int(r.headers["X-DEVPI-SERIAL"])
        xom.keyfs.wait_tx_serial(commit_serial)
    headers = clean_response_headers(r)
    headers["X-DEVPI-PROXY"] = "replica"
    if r.status_code == 302:  # REDIRECT
        # rewrite primary-related location to our replica site
        primary_location = r.headers["location"]
        outside_url = request.application_url
        headers["location"] = str(
            primary_location.replace(xom.config.primary_url.url, outside_url))
    return Response(status="%s %s" % (r.status_code, r.reason),
                    app_iter=app_iter(),
                    headers=headers)


def proxy_view_to_primary(_context, request):
    xom = request.registry["xom"]
    tx = getattr(xom.keyfs, "tx", None)
    if getattr(tx, "write", False):
        raise RuntimeError("there should be no write transaction")
    return proxy_write_to_primary(xom, request)


class ReplicationErrors:
    def __init__(self):
        self.errors = dict()

    def remove(self, entry):
        self.errors.pop(entry.relpath, None)

    def add(self, error):
        self.errors[error['relpath']] = error


class FileReplicationError(Exception):
    """ raised when replicating a file from the primary failed. """
    def __init__(self, response, relpath, message=None):
        self.url = response.url
        self.status_code = response.status_code
        self.reason = response.reason
        self.relpath = relpath
        self.message = message or "failed"

    def __str__(self):
        return "FileReplicationError with %s, code=%s, reason=%s, relpath=%s, message=%s" % (
               self.url, self.status_code, self.reason, self.relpath, self.message)
