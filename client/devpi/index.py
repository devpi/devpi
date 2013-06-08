import os
import sys
import py
import json

from devpi import log
from devpi.config import parse_keyvalue_spec
from devpi.util import url as urlutil

DEFAULT_BASES = ["root/dev", ]

def index_create(hub, indexname, kvdict):
    url = hub.get_index_url(indexname)
    stage = urlutil.getpath(url)
    hub.http_api("put", url, kvdict)

def index_modify(hub, indexname, kvdict):
    url = hub.get_index_url(indexname)
    stage = urlutil.getpath(url)
    hub.http_api("patch", url, kvdict)

def index_delete(hub, indexname):
    url = hub.get_index_url(indexname)
    stage = urlutil.getpath(url)
    hub.http_api("delete", url, None)

def index_list(hub, indexname):
    url = hub.get_user_url() + "/"
    res = hub.http_api("get", url, None)
    for name in res["result"]:
        hub.info(name)

def main(hub, args):
    hub.requires_login()
    indexname = args.indexname
    kvdict = parse_keyvalue_spec(args.keyvalues)
    if not args.list and not indexname:
        hub.fatal("need to specify indexname")
    if args.create:
        return index_create(hub, indexname, kvdict)
    if args.modify:
        return index_modify(hub, indexname, kvdict)
    if args.delete:
        return index_delete(hub, indexname)
    if args.list:
        return index_list(hub, indexname)
