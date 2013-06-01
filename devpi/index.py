import os
import sys
import py
import json

from devpi import log

DEFAULT_UPSTREAMS = ["int/dev", "ext/pypi"]

def getdict(keyvalues):
    d = {}
    for x in keyvalues:
        key, val = x.split("=", 1)
        if key not in ("upstreams", ):
            raise KeyError("not a valid key: %s" % key)
        d[key] = val
    upstreams = d.get("upstreams", None)
    if upstreams is None:
        upstreams = DEFAULT_UPSTREAMS
    else:
        upstreams = list(filter(None, upstreams.split(",")))
    d["upstreams"] = upstreams
    return d

def create_index(hub, indexname):
    url = hub.get_index_url(indexname)
    hub.info("creating index: %s" % url)
    r = hub.http.put(url)
    if r.status_code == 201:
        hub.info("index created: %s" % url)
        for name, val in r.json().items():
            hub.info("  %s = %s" % (name, val))
    else:
        hub.error("failed to create %r index, server returned %s: %s" %(
                  indexname, r.status_code, r.reason))
        return 1

def indexadd(hub, args):
    return create_index(hub, args.indexname)

