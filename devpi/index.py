import os
import sys
import py
import json

from devpi import log
from devpi.use import getconfig

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

def create_index(hub, args):
    d = dict(indexname=args.indexname[0],
             **getdict(args.keyvalues))
    r = hub.http_post(hub.config.indexadmin, d)
    assert r.status_code == 201

def main(hub, args):
    if args.create:
        create_index(hub, args)

