
import os
import py

from devpi.util import version as verutil
from devpi.util import url as urlutil
from pkg_resources import parse_version

from devpi import log
import posixpath

def out_index(hub, data):
    for name in sorted(data):
        hub.info(name)

def out_project(hub, data, name):
    versions = list(data)
    def cmpversion(x, y):
        return cmp(parse_version(x), parse_version(y))

    index = hub.current.index[len(hub.current.rooturl):]

    versions.sort(cmp=cmpversion)
    for version in reversed(versions):
        verdata = data[version]
        #hub.info("%s-%s:" % (name, version))
        files = verdata.get("+files")
        if files is not None:
            for fn in files:
                origin = files[fn]
                if version.startswith("egg="):
                    origin = "%s (%s) " % (origin, version)
                if origin.startswith(index):
                    hub.info(origin)
                else:
                    hub.line(origin)

def main(hub, args):
    current = hub.current
    args = hub.args

    if not args.spec:
        data = getjson(hub, None)
        out_index(hub, data["result"])
    else:
        data = getjson(hub, args.spec)
        out_project(hub, data["result"], args.spec)

def getjson(hub, path):
    current = hub.current
    if not path:
        check_verify_current(hub)
        url = hub.get_index_url()
    else:
        url = urlutil.joinpath(hub.get_index_url(), path) + "/"
    return hub.http_api("get", url, quiet=True)

def check_verify_current(hub):
    if not hub.current.index:
        hub.fatal("cannot use relative path without an active index")
