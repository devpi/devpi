import os
import sys
import py
import json

from devpi import log
from devpi.config import parse_keyvalue_spec
from devpi.util import url as urlutil

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

def index_create(hub, indexname, kvdict):
    url = hub.get_index_url(indexname)
    stage = urlutil.getpath(url)
    hub.http_api("put", url, kvdict,
                 okmsg="index %r created" % stage,
                 errmsg="failed to create index %r" % stage,
    )

def index_modify(hub, indexname, kvdict):
    url = hub.get_index_url(indexname)
    stage = urlutil.getpath(url)
    hub.http_api("patch", url, kvdict,
                 okmsg="index %r modified" % stage,
                 errmsg="failed to modify index %r" % stage,
    )

def index_delete(hub, indexname):
    url = hub.get_index_url(indexname)
    stage = urlutil.getpath(url)
    hub.http_api("delete", url, None,
                 okmsg="index %r deleted" % stage,
                 errmsg="failed to delete index %r" % stage,
    )


def main(hub, args):
    hub.requires_login()
    indexname = args.indexname
    kvdict = parse_keyvalue_spec(args.keyvalues)
    if args.create:
        return index_create(hub, indexname, kvdict)
    if args.modify:
        return index_modify(hub, indexname, kvdict)
    if args.delete:
        return index_delete(hub, indexname)
