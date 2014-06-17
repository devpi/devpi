import py
from pyramid.httpexceptions import HTTPNotFound
from pyramid.view import view_config
from pyramid.response import Response

from .keyfs import load, dump
from .log import thread_push_log, threadlog
from .views import is_mutating_http_method


class MasterChangelogRequest:
    def __init__(self, request):
        self.request = request
        self.xom = request.registry["xom"]

    @view_config(route_name="/+changelog/{serial}")
    def get_changelog_entry(self):
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
                with keyfs.notifier.cv_new_transaction:
                    next_serial = keyfs.get_next_serial()
                    if serial > next_serial:
                        raise HTTPNotFound("can only wait for next serial")
                    with threadlog.around("debug",
                                          "waiting for tx%s", serial):
                        while serial >= keyfs.get_next_serial():
                            # we loop because we want control-c to get through
                            keyfs.notifier.cv_new_transaction.wait(2)
                raw_entry = keyfs._fs.get_raw_changelog_entry(serial)

        devpi_serial = keyfs.get_current_serial()
        r = Response(body=raw_entry, status=200, headers={
            str("Content-Type"): str("application/octet-stream"),
            str("X-DEVPI-SERIAL"): str(devpi_serial),
        })
        return r

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
        for key in (keyfs.STAGEFILE, keyfs.PYPIFILE_NOMD5, keyfs.PYPISTAGEFILE):
            keyfs.subscribe_on_import(key, ReplicaFileGetter(self.xom))
        while 1:
            self.thread.exit_if_shutdown()
            serial = keyfs.get_next_serial()
            url = self.master_url.joinpath("+changelog", str(serial)).url
            log.info("fetching %s", url)
            try:
                r = session.get(url, stream=True)
            except Exception:
                log.exception("error fetching %s", url)
            else:
                if r.status_code == 200:
                    try:
                        entry = load(r.raw)
                    except Exception:
                        log.error("could not read answer %s", url)
                    else:
                        log.info("importing changelog entry %s", serial)
                        keyfs.import_changelog_entry(serial, entry)
                        serial += 1
                        continue
                else:
                    log.debug("%s: failed fetching %s", r.status_code, url)
            # we got an error, let's wait a bit
            self.thread.sleep(60.0)


class PyPIProxy(object):
    def __init__(self, http, master_url):
        self._url = master_url.joinpath("root/pypi/+name2serials").url
        self._http = http

    def list_packages_with_serial(self):
        try:
            r = self._http.get(self._url, stream=True)
        except self._http.RequestException:
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
        cache = ev.value
        name = cache["projectname"]
        name2serials = self.xom.pypimirror.name2serials
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


def proxy_write_to_master(xom, request):
    """ relay modifying http requests to master and wait until
    the change is replicated back.
    """
    url = xom.config.master_url.joinpath(request.path).url
    http = xom._httpsession
    with threadlog.around("info", "relaying: %s %s", request.method,
    url):
        r = http.request(request.method, url,
                         data=request.body,
                         headers=request.headers)
    if r.status_code < 400:
        commit_serial = int(r.headers["X-DEVPI-SERIAL"])
        xom.keyfs.notifier.wait_tx_serial(commit_serial)
    headers = r.headers.copy()
    headers[str("X-DEVPI-PROXY")] = str("replica")
    return Response(status=r.status_code,
                    body=r.content,
                    headers=headers)

class ReplicaFileGetter:
    def __init__(self, xom):
        self.xom = xom

    def __call__(self, key, val):
        relpath = key.relpath
        entry = self.xom.filestore.get_file_entry_raw(key, val)
        if entry.file_exists():
            if entry.md5 and entry.md5 != entry.file_md5():
                threadlog.info("local file has different md5, forgetting: %s",
                            entry._filepath)
            else:
                return
        elif entry.last_modified is None:
            return  # file does not exist remotely

        threadlog.info("retrieving file from master: %s", relpath)
        url = self.xom.config.master_url.joinpath(relpath).url
        r = self.xom.httpget(url, allow_redirects=True)
        if r.status_code != 200:
            threadlog.error("got %s from upstream", r.status_code)
            return
        entry.file_set_content(r.content, last_modified=-1)
