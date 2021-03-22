import os
import contextlib
import itsdangerous
import secrets
import threading
import time
import traceback
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
from .filestore import FileEntry
from .fileutil import BytesForHardlink, dumps, loads
from .log import thread_push_log, threadlog
from .views import H_MASTER_UUID, make_uuid_headers
from .model import UpstreamError


devpiweb_hookimpl = HookimplMarker("devpiweb")


H_REPLICA_UUID = str("X-DEVPI-REPLICA-UUID")
H_REPLICA_OUTSIDE_URL = str("X-DEVPI-REPLICA-OUTSIDE-URL")
H_REPLICA_FILEREPL = str("X-DEVPI-REPLICA-FILEREPL")
H_EXPECTED_MASTER_ID = str("X-DEVPI-EXPECTED-MASTER-ID")

MAX_REPLICA_BLOCK_TIME = 30.0
REPLICA_USER_NAME = "+replica"
REPLICA_REQUEST_TIMEOUT = MAX_REPLICA_BLOCK_TIME * 1.25
REPLICA_MULTIPLE_TIMEOUT = REPLICA_REQUEST_TIMEOUT / 2
REPLICA_AUTH_MAX_AGE = REPLICA_REQUEST_TIMEOUT + 0.1
MAX_REPLICA_CHANGES_SIZE = 5 * 1024 * 1024


notset = object()


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
    if not request.registry["xom"].is_master():
        log_replica_token_error(
            request, "Replica token detected, but role isn't master.")
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


class MasterChangelogRequest:
    MAX_REPLICA_BLOCK_TIME = MAX_REPLICA_BLOCK_TIME
    MAX_REPLICA_CHANGES_SIZE = MAX_REPLICA_CHANGES_SIZE
    REPLICA_MULTIPLE_TIMEOUT = REPLICA_MULTIPLE_TIMEOUT

    def __init__(self, request):
        self.request = request
        self.xom = request.registry["xom"]

    @contextlib.contextmanager
    def update_replica_status(self, serial):
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
                "last-request": time.time(),
                "outside-url": headers.get(H_REPLICA_OUTSIDE_URL),
            }
            try:
                yield
            finally:
                polling_replicas[uuid]["last-request"] = time.time()
                polling_replicas[uuid]["in-request"] = False
        else:  # just a regular request
            yield

    def verify_master(self):
        if not self.xom.is_master():
            raise HTTPForbidden("Replication protocol disabled")
        expected_uuid = self.request.headers.get(H_EXPECTED_MASTER_ID, None)
        master_uuid = self.xom.config.get_master_uuid()
        # we require the header but it is allowed to be empty
        # (during initialization)
        if expected_uuid is None:
            msg = "replica sent no %s header" % H_EXPECTED_MASTER_ID
            threadlog.error(msg)
            raise HTTPBadRequest(msg)

        if expected_uuid and expected_uuid != master_uuid:
            threadlog.error("expected %r as master_uuid, replica sent %r", master_uuid,
                      expected_uuid)
            raise HTTPBadRequest("expected %s as master_uuid, replica sent %s" %
                                 (master_uuid, expected_uuid))

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

        self.verify_master()

        serial = int(self.request.matchdict["serial"])

        with self.update_replica_status(serial):
            keyfs = self.xom.keyfs
            self._wait_for_serial(serial)

            raw_entry = keyfs.tx.conn.get_raw_changelog_entry(serial)

            devpi_serial = keyfs.get_current_serial()
            r = Response(body=raw_entry, status=200, headers={
                str("Content-Type"): str("application/octet-stream"),
                str("X-DEVPI-SERIAL"): str(devpi_serial),
            })
            return r

    @view_config(route_name="/+changelog/{serial}-")
    def get_multiple_changes(self):
        self.verify_master()

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
                    threadlog.debug('Changelog raw size %s' % raw_size)
                    break
                if (now - start_time) > (self.REPLICA_MULTIPLE_TIMEOUT):
                    threadlog.debug('Changelog timeout %s' % raw_size)
                    break
            raw_entry = dumps(all_changes)
            r = Response(body=raw_entry, status=200, headers={
                str("Content-Type"): str("application/octet-stream"),
                str("X-DEVPI-SERIAL"): str(devpi_serial),
            })
            return r

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
                    headers={str("X-DEVPI-SERIAL"):
                             str(keyfs.get_current_serial())})
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
        for key in (keyfs.STAGEFILE, keyfs.PYPIFILE_NOMD5):
            keyfs.subscribe_on_import(key, self.shared_data.on_import)
        self.file_replication_threads = []
        num_threads = xom.config.file_replication_threads
        threadlog.info("Using %s file download threads." % num_threads)
        for i in range(num_threads):
            frt = FileReplicationThread(xom, self.shared_data)
            self.file_replication_threads.append(frt)
            xom.thread_pool.register(frt)
        self.initial_queue_thread = InitialQueueThread(xom, self.shared_data)
        xom.thread_pool.register(self.initial_queue_thread)
        self.master_auth = xom.config.master_auth
        self.master_url = xom.config.master_url
        self._master_serial = None
        self._master_serial_timestamp = None
        self.started_at = None
        # updated whenever we try to connect to the master
        self.master_contacted_at = None
        # updated on valid reply or 202 from master
        self.update_from_master_at = None
        # set whenever the master serial and current replication serial match
        self.replica_in_sync_at = None
        self.session = self.xom.new_http_session("replica")
        self.initial_fetch = True

    @cached_property
    def auth_serializer(self):
        return get_auth_serializer(self.xom.config)

    def get_master_serial(self):
        return self._master_serial

    def get_master_serial_timestamp(self):
        return self._master_serial_timestamp

    def update_master_serial(self, serial):
        now = time.time()
        # record that we got a reply from the master, so we can produce status
        # information about the connection to master
        self.update_from_master_at = now
        if self.xom.keyfs.get_current_serial() == serial:
            with self.shared_data._replica_in_sync_cv:
                self.replica_in_sync_at = now
                self.shared_data._replica_in_sync_cv.notify_all()
        if self._master_serial is not None and serial <= self._master_serial:
            if serial < self._master_serial:
                self.log.error(
                    "Got serial %s from master which is smaller than last "
                    "recorded serial %s." % (serial, self._master_serial))
            return
        self._master_serial = serial
        self._master_serial_timestamp = now

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
        uuid, master_uuid = make_uuid_headers(config.nodeinfo)
        assert uuid != master_uuid
        try:
            self.master_contacted_at = time.time()
            token = self.auth_serializer.dumps(uuid)
            r = self.session.get(
                url,
                allow_redirects=False,
                auth=self.master_auth,
                headers={
                    H_REPLICA_UUID: uuid,
                    H_EXPECTED_MASTER_ID: master_uuid,
                    H_REPLICA_OUTSIDE_URL: config.args.outside_url,
                    str('Authorization'): 'Bearer %s' % token},
                timeout=self.REPLICA_REQUEST_TIMEOUT)
        except Exception as e:
            msg = ''.join(traceback.format_exception_only(e.__class__, e)).strip()
            log.error("error fetching %s: %s", url, msg)
            return False

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
        master_uuid = config.get_master_uuid()
        remote_master_uuid = r.headers.get(H_MASTER_UUID)
        if not remote_master_uuid:
            # we don't fatally leave the process because
            # it might just be a temporary misconfiguration
            # for example of a nginx frontend
            log.error("remote provides no %r header, running "
                      "<devpi-server-2.1?"
                      " headers were: %s", H_MASTER_UUID, r.headers)
            self.thread.sleep(self.ERROR_SLEEP)
            return True
        if master_uuid and remote_master_uuid != master_uuid:
            # we got a master_uuid and it is not the one we
            # expect, we are replicating for -- it's unlikely this heals
            # itself.  It's thus better to die and signal we can't operate.
            log.error("FATAL: master UUID %r does not match "
                      "expected master UUID %r. EXITTING.",
                      remote_master_uuid, master_uuid)
            # force exit of the process
            os._exit(3)

        try:
            remote_serial = int(r.headers["X-DEVPI-SERIAL"])
        except Exception as e:
            msg = ''.join(traceback.format_exception_only(e.__class__, e)).strip()
            log.error("error fetching %s: %s", url, msg)
            return False

        if r.status_code == 200:
            try:
                handler(r)
            except Exception:
                log.exception("could not process: %s", r.url)
            else:
                # we successfully received data so let's
                # record the master_uuid for future consistency checks
                if not master_uuid:
                    self.xom.config.set_master_uuid(remote_master_uuid)
                # also record the current master serial for status info
                self.update_master_serial(remote_serial)
                return True
        elif r.status_code == 202:
            remote_serial = int(r.headers["X-DEVPI-SERIAL"])
            log.debug("%s: trying again %s\n", r.status_code, url)
            # also record the current master serial for status info
            self.update_master_serial(remote_serial)
            return True
        return False

    def handler_single(self, response, serial):
        changes, rel_renames = loads(response.content)
        self.xom.keyfs.import_changes(serial, changes)

    def fetch_single(self, serial):
        url = self.master_url.joinpath("+changelog", str(serial)).url
        return self.fetch(
            partial(self.handler_single, serial=serial),
            url)

    def handler_multi(self, response):
        all_changes = loads(response.content)
        for serial, changes in all_changes:
            self.xom.keyfs.import_changes(serial, changes)

    def fetch_multi(self, serial):
        url = self.master_url.joinpath("+changelog", "%s-" % serial).url
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
                        threadlog.info("File download queue size ~ %s" % qsize)
            except mythread.Shutdown:
                raise
            except:
                self.log.exception(
                    "Unhandled exception in replica thread.")
                self.thread.sleep(1.0)

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
        self.importer = ImportFileReplica(self.xom, self.errors)
        self._replica_in_sync_cv = threading.Condition()
        self.last_added = None
        self.last_errored = None
        self.last_processed = None

    def on_import(self, conn, serial, key, val, back_serial):
        # Do not queue anything until we have been in sync for the first
        # time. The InitialQueueThread will queue in one go on initial sync
        with self._replica_in_sync_cv:
            if self.xom.replica_thread.replica_in_sync_at is None:
                return
        try:
            is_from_mirror = self.is_from_mirror(key)
        except KeyError:
            stage = self.xom.model.getstage(
                key.params['user'], key.params['index'])
            self.index_types.put(stage.name, stage.ixconfig['type'])
            is_from_mirror = self.is_from_mirror(key)
        # note the negated serial for the PriorityQueue
        self.queue.put((
            is_from_mirror, -serial, key.relpath, key.name, val, back_serial))
        self.last_added = time.time()

    def next_ts(self, delay):
        return time.time() + delay

    def add_errored(self, is_from_mirror, serial, key, keyname, value, back_serial, ts=None, delay=11):
        if ts is None:
            ts = self.next_ts(min(delay, self.ERROR_QUEUE_MAX_DELAY))
        # this priority queue is ordered by time stamp
        self.error_queue.put(
            (ts, delay, is_from_mirror, serial, key, keyname, value, back_serial))
        self.last_errored = time.time()

    def is_from_mirror(self, key, default=notset):
        index_name = "%s/%s" % (key.params['user'], key.params['index'])
        result = self.index_types.get(index_name)
        if result is None:
            if default is notset:
                raise KeyError
            return default
        return result == 'mirror'

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
        (ts, delay, is_from_mirror, serial, key, keyname, value, back_serial) = info
        try:
            if self.is_in_future(ts):
                # not current yet, so re-add it
                self.add_errored(
                    is_from_mirror, serial, key, keyname, value, back_serial,
                    ts=ts, delay=delay)
                return
            handler(is_from_mirror, serial, key, keyname, value, back_serial)
        except Exception:
            # another failure, re-add with longer delay
            self.add_errored(
                is_from_mirror, serial, key, keyname, value, back_serial,
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
        (is_from_mirror, serial, key, keyname, value, back_serial) = info
        # negate again, because it was negated for the PriorityQueue
        serial = -serial
        try:
            handler(is_from_mirror, serial, key, keyname, value, back_serial)
        except Exception as e:
            threadlog.warn(
                "Error during file replication: %s" % ''.join(
                    traceback.format_exception_only(e.__class__, e)).strip())
            self.add_errored(is_from_mirror, serial, key, keyname, value, back_serial)
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
        ('devpi_server_replica_indextypes_cache_evictions', 'counter', indextypes_cache.evictions),
        ('devpi_server_replica_indextypes_cache_hits', 'counter', indextypes_cache.hits),
        ('devpi_server_replica_indextypes_cache_lookups', 'counter', indextypes_cache.lookups),
        ('devpi_server_replica_indextypes_cache_misses', 'counter', indextypes_cache.misses),
        ('devpi_server_replica_indextypes_cache_size', 'gauge', indextypes_cache.size)])
    return result


def includeme(config):
    # config.add_request_method(devpi_token_utility, reify=True)
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

    def handler(self, is_from_mirror, serial, key, keyname, value, back_serial):
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
        with keyfs._storage.get_connection(write=True) as conn:
            self.shared_data.importer(
                conn, serial, typedkey, value, back_serial, self.session)
            conn.commit_files_without_increasing_serial()
        entry = self.xom.filestore.get_file_entry_from_key(typedkey, meta=value)
        if not entry.project or not entry.version:
            return
        with keyfs.transaction(write=False, at_serial=serial):
            user = entry.key.params['user']
            index = entry.key.params['index']
            stage = self.xom.model.getstage(user, index)
            if stage is None:
                return
            stage.offline = True
            name = normalize_name(entry.project)
            try:
                linkstore = stage.get_linkstore_perstage(name, entry.version)
            except (stage.MissesRegistration, stage.UpstreamError):
                if is_from_mirror:
                    return
                raise
            links = linkstore.get_links(basename=entry.basename)
            for link in links:
                self.xom.config.hook.devpiserver_on_replicated_file(
                    stage=stage, project=name, version=entry.version, link=link,
                    serial=serial, back_serial=back_serial,
                    is_from_mirror=is_from_mirror)

    def tick(self):
        self.shared_data.process_next(self.handler)

    def thread_run(self):
        thread_push_log("[FREP]")
        last_time = time.time()
        master_serial = None
        serial = -1
        while 1:
            try:
                self.tick()
                if time.time() - last_time > 5:
                    last_time = time.time()
                    master_serial = self.xom.replica_thread.get_master_serial()
                    serial = self.xom.keyfs.get_current_serial()
                if master_serial is not None and serial < master_serial:
                    # be nice to get metadata in sync first
                    self.thread.sleep(5)
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
        threadlog.info("Queuing files for possible download from master")
        keys = (keyfs.get_key('PYPIFILE_NOMD5'), keyfs.get_key('STAGEFILE'))
        last_time = time.time()
        processed = 0
        queued = 0
        # wait until we are in sync for the first time
        with self.shared_data._replica_in_sync_cv:
            self.shared_data._replica_in_sync_cv.wait()
        with keyfs.transaction(write=False) as tx:
            for user in self.xom.model.get_userlist():
                for stage in user.getstages():
                    self.shared_data.index_types.put(stage.name, stage.ixconfig['type'])
            relpaths = tx.iter_relpaths_at(keys, tx.at_serial)
            for item in relpaths:
                if item.value is None:
                    continue
                while self.shared_data.queue.qsize() > 1000:
                    # let the queue be processed before filling it further
                    self.thread.sleep(5)
                if time.time() - last_time > 5:
                    last_time = time.time()
                    threadlog.info(
                        "Processed a total of %s files and queued %s so far."
                        % (processed, queued))
                processed = processed + 1
                key = keyfs.get_key_instance(item.keyname, item.relpath)
                entry = FileEntry(key, item.value)
                if entry.file_exists() or not entry.last_modified:
                    continue
                is_from_mirror = self.shared_data.is_from_mirror(key, False)
                # note the negated serial for the PriorityQueue
                # the index_type boolean will prioritize non mirrors
                self.shared_data.queue.put((
                    is_from_mirror, -item.serial, item.relpath,
                    item.keyname, item.value, item.back_serial))
                queued = queued + 1
        threadlog.info(
            "Queued %s of %s files for possible download from master"
            % (queued, processed))


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

        with self.xom.keyfs.transaction(write=False):
            mirror_stage = self.xom.model.getstage(username, index)
            if mirror_stage and mirror_stage.ixconfig["type"] == "mirror":
                cache_projectnames = mirror_stage.cache_projectnames.get_inplace()
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


def proxy_request_to_master(xom, request, stream=False):
    master_url = xom.config.master_url
    url = master_url.joinpath(request.path).url
    assert url.startswith(master_url.url)
    http = xom._httpsession
    with threadlog.around("info", "relaying: %s %s", request.method, url):
        try:
            headers = clean_request_headers(request)
            try:
                length = int(headers.get('Content-Length'))
            except (ValueError, TypeError):
                length = None
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
            raise UpstreamError("proxy-write-to-master %s: %s" % (url, e))


def proxy_write_to_master(xom, request):
    """ relay modifying http requests to master and wait until
    the change is replicated back.
    """
    r = proxy_request_to_master(xom, request, stream=True)
    # for redirects, the body is already read and stored in the ``next``
    # attribute (see requests.sessions.send)
    if r.raw.closed and r.next:
        app_iter = (r.next.body,)
    else:
        app_iter = r.raw.stream()
    if r.status_code < 400:
        commit_serial = int(r.headers["X-DEVPI-SERIAL"])
        xom.keyfs.wait_tx_serial(commit_serial)
    headers = clean_response_headers(r)
    headers[str("X-DEVPI-PROXY")] = str("replica")
    if r.status_code == 302:  # REDIRECT
        # rewrite master-related location to our replica site
        master_location = r.headers["location"]
        outside_url = request.application_url
        headers[str("location")] = str(
            master_location.replace(xom.config.master_url.url, outside_url))
    return Response(status="%s %s" %(r.status_code, r.reason),
                    app_iter=app_iter,
                    headers=headers)


def proxy_view_to_master(context, request):
    xom = request.registry["xom"]
    tx = getattr(xom.keyfs, "tx", None)
    assert getattr(tx, "write", False) is False, "there should be no write transaction"
    return proxy_write_to_master(xom, request)


class ReplicationErrors:
    def __init__(self):
        self.errors = dict()

    def remove(self, entry):
        self.errors.pop(entry.relpath, None)

    def add(self, error):
        self.errors[error['relpath']] = error


class ImportFileReplica:
    def __init__(self, xom, errors):
        self.xom = xom
        self.errors = errors
        self.file_search_path = self.xom.config.replica_file_search_path
        self.use_hard_links = self.xom.config.hard_links
        self.uuid, master_uuid = make_uuid_headers(xom.config.nodeinfo)
        assert self.uuid != master_uuid

    @cached_property
    def auth_serializer(self):
        return get_auth_serializer(self.xom.config)

    def find_pre_existing_file(self, key, val):
        if self.file_search_path is None:
            return
        if not os.path.exists(self.file_search_path):
            threadlog.error(
                "path for existing files doesn't exist: %s",
                self.file_search_path)
        path = os.path.join(self.file_search_path, key.relpath)
        if os.path.exists(path):
            threadlog.info("checking existing file: %s", path)
            with open(path, "rb") as f:
                data = f.read()
            if self.use_hard_links:
                # wrap the data for additional attribute
                data = BytesForHardlink(data)
                data.devpi_srcpath = path
            return data
        else:
            threadlog.info("path for existing file not found: %s", path)

    def __call__(self, conn, serial, key, val, back_serial, session):
        threadlog.debug("ImportFileReplica for %s, %s", key, val)
        relpath = key.relpath
        entry = self.xom.filestore.get_file_entry_from_key(key, meta=val)
        file_exists = conn.io_file_exists(entry._storepath)
        if val is None:
            if back_serial >= 0:
                # file was deleted, still might never have been replicated
                if file_exists:
                    threadlog.debug("mark for deletion: %s", entry._storepath)
                    conn.io_file_delete(entry._storepath)
            self.errors.remove(entry)
            return
        if file_exists or entry.last_modified is None:
            # we have a file or there is no remote file
            self.errors.remove(entry)
            return

        content = self.find_pre_existing_file(key, val)
        if content is not None:
            err = entry.check_checksum(content)
            if not err:
                conn.io_file_set(entry._storepath, content)
                self.errors.remove(entry)
                return
            else:
                threadlog.error(str(err))

        threadlog.info(
            "retrieving file from master for serial %s: %s", serial, relpath)
        url = self.xom.config.master_url.joinpath(relpath).url
        # we perform the request with a special header so that
        # the master can avoid -getting "volatile" links
        token = self.auth_serializer.dumps(self.uuid)
        r = session.get(
            url, allow_redirects=False,
            headers={
                H_REPLICA_FILEREPL: str("YES"),
                H_REPLICA_UUID: self.uuid,
                str('Authorization'): 'Bearer %s' % token},
            timeout=self.xom.config.args.request_timeout)
        if r.status_code == 302:
            # mirrors might redirect to external file when
            # mirror_use_external_urls is set
            threadlog.warn("ignoring because of redirection to external URL: %s",
                           relpath)
            self.errors.remove(entry)
            return
        if r.status_code == 410:
            # master indicates Gone for files which were later deleted
            threadlog.warn("ignoring because of later deletion: %s",
                           relpath)
            self.errors.remove(entry)
            return

        if r.status_code in (404, 502):
            stagename = '/'.join(relpath.split('/')[:2])
            with self.xom.keyfs.transaction(write=False):
                stage = self.xom.model.getstage(stagename)
            if stage.ixconfig['type'] == 'mirror':
                threadlog.warn(
                    "ignoring file which couldn't be retrieved from mirror index '%s': %s" % (
                        stagename, relpath))
                self.errors.remove(entry)
                return

        if r.status_code != 200:
            threadlog.error(
                "error downloading '%s' from master, will be retried later: "
                "%s" % (relpath, r.reason))
            # add the error for the UI
            self.errors.add(dict(
                url=r.url,
                message=r.reason,
                relpath=entry.relpath))
            # and raise for retrying later
            raise FileReplicationError(r, relpath)

        err = entry.check_checksum(r.content)
        if err:
            # the file we got is different, it may have changed later.
            # we remember the error and move on
            threadlog.error(
                "checksum mismatch for '%s', will be retried later: "
                "%s" % (relpath, r.reason))
            self.errors.add(dict(
                url=r.url,
                message=str(err),
                relpath=entry.relpath))
            return
        # in case there were errors before, we can now remove them
        self.errors.remove(entry)
        conn.io_file_set(entry._storepath, r.content)


class FileReplicationError(Exception):
    """ raised when replicating a file from the master failed. """
    def __init__(self, response, relpath, message=None):
        self.url = response.url
        self.status_code = response.status_code
        self.reason = response.reason
        self.relpath = relpath
        self.message = message or "failed"

    def __str__(self):
        return "FileReplicationError with %s, code=%s, reason=%s, relpath=%s, message=%s" % (
               self.url, self.status_code, self.reason, self.relpath, self.message)
