import py
from pyramid.httpexceptions import HTTPNotFound
from pyramid.view import view_config
from pyramid.response import Response
from .keyfs import load, dump
from .mythread import XOMThread

import logging

log = logging.getLogger(__name__)

class MasterChangelogRequest:
    def __init__(self, request):
        self.request = request
        self.xom = request.registry["xom"]


    @view_config(route_name="/+changelog/{serial}")
    def get_changelog_entry(self):
        serial = self.request.matchdict["serial"]
        if serial.lower() == "nop":
            raw_entry = b""
        else:
            try:
                serial = int(serial)
            except ValueError:
                raise HTTPNotFound("serial needs to be int")
            raw_entry = self.xom.keyfs._fs.get_raw_changelog_entry(serial)
            if not raw_entry:
                # XXX wait on a change if serial == current_serial+1
                raise HTTPNotFound("no changelog entry for %r" %(serial))
        devpi_serial = self.xom.keyfs.get_next_serial() - 1
        r = Response(body=raw_entry, status=200, headers={
            str("Content-Type"): str("application/octet-stream"),
            str("X-DEVPI-SERIAL"): str(devpi_serial),
        })
        return r

    @view_config(route_name="/root/pypi/+name2serials")
    def get_name2serials(self):
        io = py.io.BytesIO()
        data = dump(self.xom.pypimirror.name2serials, io)
        headers = {str("Content-Type"): str("application/octet-stream")}
        return Response(body=io.getvalue(), status=200, headers=headers)


class ReplicaThread(XOMThread):
    def __init__(self, xom):
        XOMThread.__init__(self)
        self.xom = xom
        r = xom.config.args.master_url
        assert r
        r = r.rstrip("/") + "/+changelog"
        self.master_changelog_url = r
        if xom.is_replica():
            xom.keyfs.notifier.on_key_change("PYPILINKS",
                                             PypiProjectChanged(xom))

    def run(self):
        session = self.xom.new_http_session("replica")
        keyfs = self.xom.keyfs
        while 1:
            # within a replica this thread should be the only writer
            serial = keyfs.get_next_serial()
            r = session.get(self.master_changelog_url + "/%s" % serial,
                            stream=True)
            if self.is_shutting_down():
                break
            if r.status_code == 200:
                try:
                    entry = load(r.raw)
                except EOFError:
                    break
                else:
                    keyfs.import_changelog_entry(serial, entry)
                    serial += 1
            else: # we got an error, let's wait a bit
                self.xom.sleep(5.0)


class PyPIProxy(object):
    def __init__(self, xom, master_url):
        self._url = master_url.rstrip("/") + "/root/pypi/+name2serials"
        self.xom = xom

    def list_packages_with_serial(self):
        session = self.xom.new_http_session("devpi-rpc")
        r = session.get(self._url, stream=True)
        if r.status_code != 200:
            from devpi_server.main import fatal
            fatal("replica: could not get serials from remote")
        return load(r.raw)


class PypiProjectChanged:
    """ Event executed in notification thread based on a pypi link change. """
    def __init__(self, xom):
        self.xom = xom

    def __call__(self, ev):
        log.info("PypiProjectChanged %s", ev.typedkey)
        cache = ev.value
        name = cache["projectname"]
        name2serials = self.xom.pypimirror.name2serials
        cur_serial = name2serials.get(name, -1)
        if cache and cache["serial"] > cur_serial:
            name2serials[cache["projectname"]] = cache["serial"]
