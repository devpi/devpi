import os
import py
import hashlib
from pyramid.httpexceptions import HTTPNotFound, HTTPAccepted
from pyramid.view import view_config
from pyramid.response import Response

from .keyfs import load, loads, dump, get_write_file_ensure_dir
from .log import thread_push_log, threadlog
from .views import is_mutating_http_method, get_outside_url
from .model import UpstreamError


class MasterChangelogRequest:
    MAX_REPLICA_BLOCK_TIME = 30.0
    WAKEUP_INTERVAL = 2.0

    def __init__(self, request):
        self.request = request
        self.xom = request.registry["xom"]

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

        serial = self.request.matchdict["serial"]
        keyfs = self.xom.keyfs
        if serial.lower() == "nop":
            raw_entry = b""
        else:
            try:
                serial = int(serial)
            except ValueError:
                raise HTTPNotFound("serial needs to be int")
            raw_entry = keyfs._fs.get_raw_changelog_entry(serial)
            if not raw_entry:
                raw_entry = self._wait_for_entry(serial)

        devpi_serial = keyfs.get_current_serial()
        r = Response(body=raw_entry, status=200, headers={
            str("Content-Type"): str("application/octet-stream"),
            str("X-DEVPI-SERIAL"): str(devpi_serial),
        })
        return r

    def _wait_for_entry(self, serial):
        max_wakeups = self.MAX_REPLICA_BLOCK_TIME / self.WAKEUP_INTERVAL
        keyfs = self.xom.keyfs
        with keyfs.notifier.cv_new_transaction:
            next_serial = keyfs.get_next_serial()
            if serial > next_serial:
                raise HTTPNotFound("can only wait for next serial")
            with threadlog.around("debug",
                                  "waiting for tx%s", serial):
                num_wakeups = 0
                while serial >= keyfs.get_next_serial():
                    if num_wakeups >= max_wakeups:
                        raise HTTPAccepted("no new transaction yet",
                            headers={str("X-DEVPI-SERIAL"):
                                     str(keyfs.get_current_serial())})
                    # we loop because we want control-c to get through
                    keyfs.notifier.cv_new_transaction.wait(
                        self.WAKEUP_INTERVAL)
                    num_wakeups += 1
        return keyfs._fs.get_raw_changelog_entry(serial)


    @view_config(route_name="/root/pypi/+name2serials")
    def get_name2serials(self):
        io = py.io.BytesIO()
        dump(self.xom.pypimirror.name2serials, io)
        headers = {str("Content-Type"): str("application/octet-stream")}
        return Response(body=io.getvalue(), status=200, headers=headers)


class ReplicaThread:
    def __init__(self, xom):
        self.xom = xom
        self.master_url = xom.config.master_url
        if xom.is_replica():
            xom.keyfs.notifier.on_key_change("PYPILINKS",
                                             PypiProjectChanged(xom))

    def thread_run(self):
        # within a devpi replica server this thread is the only writer
        log = thread_push_log("[REP]")
        session = self.xom.new_http_session("replica")
        keyfs = self.xom.keyfs
        for key in (keyfs.STAGEFILE, keyfs.PYPIFILE_NOMD5):
            keyfs.subscribe_on_import(key, ImportFileReplica(self.xom))
        while 1:
            self.thread.exit_if_shutdown()
            serial = keyfs.get_next_serial()
            url = self.master_url.joinpath("+changelog", str(serial)).url
            log.info("fetching %s", url)
            try:
                r = session.get(url, stream=True)
            except session.Errors:
                log.exception("error fetching %s", url)
            else:
                if r.status_code == 200:
                    try:
                        entry = loads(r.raw.read())
                    except Exception:
                        log.exception("could not read answer %s", url)
                    else:
                        changes, rel_renames = entry
                        keyfs.import_changes(serial, changes)
                        serial += 1
                        continue
                elif r.status_code == 202:
                    log.debug("%s: trying again %s\n", r.status_code, url)
                    continue
                else:
                    log.debug("%s: failed fetching %s\n%s",
                              r.status_code, url, getattr(r, 'text', ''))
            # we got an error, let's wait a bit
            self.thread.sleep(5.0)


class PyPIProxy(object):
    def __init__(self, http, master_url):
        self._url = master_url.joinpath("root/pypi/+name2serials").url
        self._http = http

    def list_packages_with_serial(self):
        try:
            r = self._http.get(self._url, stream=True)
        except self._http.Errors:
            threadlog.exception("proxy request failed, no connection?")
        else:
            if r.status_code == 200:
                return load(r.raw)
        from devpi_server.main import fatal
        fatal("replica: could not get serials from remote")


class PypiProjectChanged:
    """ Event executed in notification thread based on a pypi link change. """
    def __init__(self, xom):
        self.xom = xom

    def __call__(self, ev):
        threadlog.info("PypiProjectChanged %s", ev.typedkey)
        pypimirror = self.xom.pypimirror
        name2serials = pypimirror.name2serials
        cache = ev.value
        if cache is None:  # deleted
            # derive projectname to delete from key
            name = ev.typedkey.params["name"]
            projectname = pypimirror.get_registered_name(name)
            if projectname:
                del name2serials[projectname]
            else:
                threadlog.error("project %r missing", name)
        else:
            name = cache["projectname"]
            cur_serial = name2serials.get(name, -1)
            if cache and cache["serial"] > cur_serial:
                name2serials[cache["projectname"]] = cache["serial"]


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


def proxy_write_to_master(xom, request):
    """ relay modifying http requests to master and wait until
    the change is replicated back.
    """
    master_url = xom.config.master_url
    url = master_url.joinpath(request.path).url
    http = xom._httpsession
    with threadlog.around("info", "relaying: %s %s", request.method,
    url):
        try:
            r = http.request(request.method, url,
                             data=request.body,
                             headers=request.headers,
                             allow_redirects=False)
        except http.Errors as e:
            raise UpstreamError("proxy-write-to-master %s: %s" % (url, e))
    #threadlog.debug("relay status_code: %s", r.status_code)
    #threadlog.debug("relay headers: %s", r.headers)

    if r.status_code < 400:
        commit_serial = int(r.headers["X-DEVPI-SERIAL"])
        xom.keyfs.notifier.wait_tx_serial(commit_serial)
    headers = dict()
    # remove hop by hop headers, see:
    # https://www.mnot.net/blog/2011/07/11/what_proxies_must_do
    hop_keys = set(hop_by_hop)
    connection = r.headers.get('connection')
    if connection and connection.lower() != 'close':
        hop_keys.update(x.strip().lower() for x in connection.split(','))
    for k, v in r.headers.items():
        if k.lower() in hop_keys:
            continue
        headers[k] = v
    headers[str("X-DEVPI-PROXY")] = str("replica")
    if r.status_code == 302:  # REDIRECT
        # rewrite master-related location to our replica site
        master_location = r.headers["location"]
        outside_url = get_outside_url(request, xom.config.args.outside_url)
        headers[str("location")] = str(
            master_location.replace(master_url.url, outside_url))
    return Response(status="%s %s" %(r.status_code, r.reason),
                    body=r.content,
                    headers=headers)

class ImportFileReplica:
    def __init__(self, xom):
        self.xom = xom

    def __call__(self, fswriter, key, val, back_serial):
        threadlog.debug("ImportFileReplica for %s, %s", key, val)
        relpath = key.relpath
        entry = self.xom.filestore.get_file_entry_raw(key, val)
        file_exists = os.path.exists(entry._filepath)
        if val is None:
            if back_serial >= 0:
                # file was deleted, still might never have been replicated
                if file_exists:
                    threadlog.debug("mark for deletion: %s", entry._filepath)
                    fswriter.record_rename_file(None, entry._filepath)
            return
        if file_exists or entry.last_modified is None:
            # we have a file or there is no remote file
            return

        threadlog.info("retrieving file from master: %s", relpath)
        url = self.xom.config.master_url.joinpath(relpath).url
        r = self.xom.httpget(url, allow_redirects=True)
        if r.status_code != 200:
            threadlog.error("got %s from upstream", r.status_code)
            return
        remote_md5 = hashlib.md5(r.content).hexdigest()
        if entry.md5 and entry.md5 != remote_md5:
            threadlog.error("%s: remote has md5 %s, expected %s",
                            url, remote_md5, entry.md5)
        else:
            tmppath = entry._filepath + "-tmp"
            with get_write_file_ensure_dir(tmppath) as f:
                f.write(r.content)
            fswriter.record_rename_file(tmppath, entry._filepath)
