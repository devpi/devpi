import os
import json
import contextlib
import time
from pyramid.httpexceptions import HTTPNotFound, HTTPAccepted, HTTPBadRequest
from pyramid.view import view_config
from pyramid.response import Response
from devpi_common.validation import normalize_name
from webob.headers import EnvironHeaders, ResponseHeaders

from . import mythread
from .fileutil import loads, rename
from .log import thread_push_log, threadlog
from .views import is_mutating_http_method, H_MASTER_UUID, make_uuid_headers
from .model import UpstreamError

H_REPLICA_UUID = str("X-DEVPI-REPLICA-UUID")
H_REPLICA_OUTSIDE_URL = str("X-DEVPI-REPLICA-OUTSIDE-URL")
H_REPLICA_FILEREPL = str("X-DEVPI-REPLICA-FILEREPL")
H_EXPECTED_MASTER_ID = str("X-DEVPI-EXPECTED-MASTER-ID")

MAX_REPLICA_BLOCK_TIME = 30.0


class MasterChangelogRequest:
    MAX_REPLICA_BLOCK_TIME = MAX_REPLICA_BLOCK_TIME

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
                "serial": int(serial)-1,
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

        serial = self.request.matchdict["serial"]

        with self.update_replica_status(serial):
            keyfs = self.xom.keyfs
            if serial.lower() == "nop":
                raw_entry = b""
            else:
                try:
                    serial = int(serial)
                except ValueError:
                    raise HTTPNotFound("serial needs to be int")
                raw_entry = self._wait_for_entry(serial)

            devpi_serial = keyfs.get_current_serial()
            r = Response(body=raw_entry, status=200, headers={
                str("Content-Type"): str("application/octet-stream"),
                str("X-DEVPI-SERIAL"): str(devpi_serial),
            })
            return r

    def _wait_for_entry(self, serial):
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
        return keyfs.tx.conn.get_raw_changelog_entry(serial)


class ReplicaThread:
    REPLICA_REQUEST_TIMEOUT = MAX_REPLICA_BLOCK_TIME * 1.25
    ERROR_SLEEP = 50

    def __init__(self, xom):
        self.xom = xom
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

    def tick(self):
        log = self.log
        keyfs = self.xom.keyfs
        config = self.xom.config
        self.thread.exit_if_shutdown()
        serial = keyfs.get_next_serial()
        url = self.master_url.joinpath("+changelog", str(serial)).url
        log.info("fetching %s", url)
        uuid, master_uuid = make_uuid_headers(config.nodeinfo)
        assert uuid != master_uuid
        try:
            self.master_contacted_at = time.time()
            r = self.session.get(url, headers={
                H_REPLICA_UUID: uuid,
                H_EXPECTED_MASTER_ID: master_uuid,
                H_REPLICA_OUTSIDE_URL: config.args.outside_url,
            }, timeout=self.REPLICA_REQUEST_TIMEOUT)
            remote_serial = int(r.headers["X-DEVPI-SERIAL"])
        except Exception as e:
            log.error("error fetching %s: %s", url, str(e))
        else:
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
                return
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
                    changes, rel_renames = loads(r.content)
                    keyfs.import_changes(serial, changes)
                except Exception:
                    log.exception("could not process: %s", r.url)
                else:
                    # we successfully received data so let's
                    # record the master_uuid for future consistency checks
                    if not master_uuid:
                        self.xom.config.set_master_uuid(remote_master_uuid)
                    # also record the current master serial for status info
                    self.update_master_serial(remote_serial)
                    return
            elif r.status_code == 202:
                log.debug("%s: trying again %s\n", r.status_code, url)
                # also record the current master serial for status info
                self.update_master_serial(remote_serial)
                return
            else:
                log.error("%s: failed fetching %s", r.status_code, url)
        # we got an error, let's wait a bit
        self.thread.sleep(5.0)

    def thread_run(self):
        # within a devpi replica server this thread is the only writer
        self.started_at = time.time()
        self.log = thread_push_log("[REP]")
        self.session = self.xom.new_http_session("replica")
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
            if mirror_stage.ixconfig["type"] == "mirror":
                cache_projectnames = mirror_stage.cache_projectnames.get_inplace()
                if cache is None:  # deleted
                    cache_projectnames.discard(project)
                else:
                    cache_projectnames.add(project)


def tween_replica_proxy(handler, registry):
    xom = registry["xom"]
    def handle_replica_proxy(request):
        assert not hasattr(xom.keyfs, "tx"), "no tx should be ongoing"
        if is_mutating_http_method(request.method):
            return proxy_write_to_master(xom, request)
        else:
            return handler(request)
    return handle_replica_proxy


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


def proxy_request_to_master(xom, request, stream=False):
    master_url = xom.config.master_url
    url = master_url.joinpath(request.path).url
    assert url.startswith(master_url.url)
    http = xom._httpsession
    with threadlog.around("info", "relaying: %s %s", request.method, url):
        try:
            return http.request(request.method, url,
                                data=request.body,
                                headers=clean_request_headers(request),
                                stream=stream,
                                allow_redirects=False)
        except http.Errors as e:
            raise UpstreamError("proxy-write-to-master %s: %s" % (url, e))


def proxy_write_to_master(xom, request):
    """ relay modifying http requests to master and wait until
    the change is replicated back.
    """
    r = proxy_request_to_master(xom, request, stream=True)
    body = r.raw.read()
    #threadlog.debug("relay status_code: %s", r.status_code)
    #threadlog.debug("relay headers: %s", r.headers)
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
                    body=body,
                    headers=headers)


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

    def __call__(self, fswriter, key, val, back_serial):
        threadlog.debug("ImportFileReplica for %s, %s", key, val)
        relpath = key.relpath
        entry = self.xom.filestore.get_file_entry_raw(key, val)
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

        threadlog.info("retrieving file from master: %s", relpath)
        url = self.xom.config.master_url.joinpath(relpath).url
        # we perform the request with a special header so that
        # the master can avoid -getting "volatile" links
        r = self.xom.httpget(url, allow_redirects=True, extra_headers=
                             {H_REPLICA_FILEREPL: str("YES")})
        if r.status_code == 410:
            # master indicates Gone for files which were later deleted
            threadlog.warn("ignoring because of later deletion: %s",
                           relpath)
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
        self.relpath = relpath
        self.message = message or "failed"

    def __str__(self):
        return "FileReplicationError with %s, code=%s, relpath=%s, message=%s" % (
               self.url, self.status_code, self.relpath, self.message)
