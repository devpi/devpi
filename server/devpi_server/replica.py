import py
from pyramid.httpexceptions import HTTPNotFound
from pyramid.view import view_config
from pyramid.response import Response

from .keyfs import load, dump
from .log import thread_push_log, threadlog


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
