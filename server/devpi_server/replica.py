import os
import json
import contextlib
import time
from functools import partial
from pyramid.httpexceptions import HTTPNotFound, HTTPAccepted, HTTPBadRequest
from pyramid.httpexceptions import HTTPForbidden
from pyramid.view import view_config
from pyramid.response import Response
from devpi_common.validation import normalize_name
from webob.headers import EnvironHeaders, ResponseHeaders

from . import mythread
from .fileutil import BytesForHardlink, dumps, loads, rename
from .log import thread_push_log, threadlog
from .views import H_MASTER_UUID, make_uuid_headers
from .model import UpstreamError

H_REPLICA_UUID = str("X-DEVPI-REPLICA-UUID")
H_REPLICA_OUTSIDE_URL = str("X-DEVPI-REPLICA-OUTSIDE-URL")
H_REPLICA_FILEREPL = str("X-DEVPI-REPLICA-FILEREPL")
H_EXPECTED_MASTER_ID = str("X-DEVPI-EXPECTED-MASTER-ID")

MAX_REPLICA_BLOCK_TIME = 30.0
REPLICA_REQUEST_TIMEOUT = MAX_REPLICA_BLOCK_TIME * 1.25
REPLICA_MULTIPLE_TIMEOUT = REPLICA_REQUEST_TIMEOUT / 2
MAX_REPLICA_CHANGES_SIZE = 5 * 1024 * 1024


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
            arrived = keyfs.wait_tx_serial(serial, timeout=self.MAX_REPLICA_BLOCK_TIME)
            if not arrived:
                raise HTTPAccepted("no new transaction yet",
                    headers={str("X-DEVPI-SERIAL"):
                             str(keyfs.get_current_serial())})
        return serial


class ReplicaThread:
    REPLICA_REQUEST_TIMEOUT = REPLICA_REQUEST_TIMEOUT
    ERROR_SLEEP = 50

    def __init__(self, xom):
        self.xom = xom
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
            self.replica_in_sync_at = now
        if self._master_serial is not None and serial <= self._master_serial:
            if serial < self._master_serial:
                self.log.error(
                    "Got serial %s from master which is smaller than last "
                    "recorded serial %s." % (serial, self._master_serial))
            return
        self._master_serial = serial
        self._master_serial_timestamp = now

    def fetch(self, handler, url):
        log = self.log
        config = self.xom.config
        log.info("fetching %s", url)
        uuid, master_uuid = make_uuid_headers(config.nodeinfo)
        assert uuid != master_uuid
        try:
            self.master_contacted_at = time.time()
            r = self.session.get(
                url,
                auth=self.master_auth,
                headers={
                    H_REPLICA_UUID: uuid,
                    H_EXPECTED_MASTER_ID: master_uuid,
                    H_REPLICA_OUTSIDE_URL: config.args.outside_url},
                timeout=self.REPLICA_REQUEST_TIMEOUT)
            remote_serial = int(r.headers["X-DEVPI-SERIAL"])
        except Exception as e:
            log.error("error fetching %s: %s", url, str(e))
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
            log.debug("%s: trying again %s\n", r.status_code, url)
            # also record the current master serial for status info
            self.update_master_serial(remote_serial)
            return True
        else:
            log.error("%s: failed fetching %s", r.status_code, url)
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

    def thread_run(self):
        # within a devpi replica server this thread is the only writer
        self.started_at = time.time()
        self.log = thread_push_log("[REP]")
        keyfs = self.xom.keyfs
        errors = ReplicationErrors(self.xom.config.serverdir)
        for key in (keyfs.STAGEFILE, keyfs.PYPIFILE_NOMD5):
            keyfs.subscribe_on_import(key, ImportFileReplica(self.xom, errors))
        while 1:
            try:
                self.tick()
            except mythread.Shutdown:
                raise
            except:
                self.log.exception(
                    "Unhandled exception in replica thread.")
                self.thread.sleep(1.0)


def register_key_subscribers(xom):
    xom.keyfs.PROJSIMPLELINKS.on_key_change(SimpleLinksChanged(xom))


class SimpleLinksChanged:
    """ Event executed in notification thread based on a pypi link change.
    It allows a replica to sync up the local full projectnames list."""
    def __init__(self, xom):
        self.xom = xom

    def __call__(self, ev):
        threadlog.info("SimpleLinksChanged %s", ev.typedkey)
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
    def __init__(self, serverdir):
        self.errorsfn = serverdir.join(".replicationerrors")
        self.errors = dict()
        self._read()

    def _read(self):
        if not self.errorsfn.exists():
            return
        with self.errorsfn.open() as f:
            try:
                self.errors = json.load(f)
            except ValueError:
                pass

    def _write(self):
        tmppath = self.errorsfn.strpath + "-tmp"
        with open(tmppath, 'w') as f:
            json.dump(self.errors, f)
        rename(tmppath, self.errorsfn.strpath)

    def remove(self, entry):
        if self.errors.pop(entry.relpath, None) is not None:
            self._write()

    def add(self, error):
        self.errors[error['relpath']] = error
        self._write()


class ImportFileReplica:
    def __init__(self, xom, errors):
        self.xom = xom
        self.errors = errors
        self.file_search_path = self.xom.config.args.replica_file_search_path
        self.use_hard_links = self.xom.config.args.hard_links

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

    def __call__(self, fswriter, key, val, back_serial):
        threadlog.debug("ImportFileReplica for %s, %s", key, val)
        relpath = key.relpath
        entry = self.xom.filestore.get_file_entry_from_key(key, meta=val)
        file_exists = fswriter.conn.io_file_exists(entry._storepath)
        if val is None:
            if back_serial >= 0:
                # file was deleted, still might never have been replicated
                if file_exists:
                    threadlog.debug("mark for deletion: %s", entry._storepath)
                    fswriter.conn.io_file_delete(entry._storepath)
            return
        if file_exists or entry.last_modified is None:
            # we have a file or there is no remote file
            return

        content = self.find_pre_existing_file(key, val)
        if content is not None:
            err = entry.check_checksum(content)
            if not err:
                fswriter.conn.io_file_set(entry._storepath, content)
                return
            else:
                threadlog.error(str(err))

        threadlog.info("retrieving file from master: %s", relpath)
        url = self.xom.config.master_url.joinpath(relpath).url
        # we perform the request with a special header so that
        # the master can avoid -getting "volatile" links
        r = self.xom.httpget(
            url, allow_redirects=True,
            extra_headers={H_REPLICA_FILEREPL: str("YES")})
        if r.status_code == 410:
            # master indicates Gone for files which were later deleted
            threadlog.warn("ignoring because of later deletion: %s",
                           relpath)
            return

        if r.status_code in (404, 502):
            stagename = '/'.join(relpath.split('/')[:2])
            stage = self.xom.model.getstage(stagename)
            if stage.ixconfig['type'] == 'mirror':
                threadlog.warn(
                    "ignoring file which couldn't be retrieved from mirror index '%s': %s" % (
                        stagename, relpath))
                return

        if r.status_code != 200:
            raise FileReplicationError(r, relpath)

        err = entry.check_checksum(r.content)
        if err:
            # the file we got is different, it may have changed later.
            # we remember the error and move on
            self.errors.add(dict(
                url=r.url,
                message=str(err),
                relpath=entry.relpath))
            return
        # in case there were errors before, we can now remove them
        self.errors.remove(entry)
        fswriter.conn.io_file_set(entry._storepath, r.content)


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
