import os
import sys
import py
import json

from devpi import log
from devpi.use import parse_keyvalue_spec
from devpi.util import url as urlutil

DEFAULT_BASES = ["root/dev", ]

def index_create(hub, indexname, kvdict):
    url = hub.get_index_url(indexname, slash=False)
    hub.http_api("put", url, kvdict)
    index_show(hub, indexname)

def index_modify(hub, indexname, kvdict):
    indexconfig = get_indexconfig_reply(hub, indexname, ok404=False)
    for name, val in kvdict.items():
        indexconfig[name] = val
        hub.info("%s changing %s: %s" %(indexname, name, val))

    url = hub.get_index_url(indexname, slash=False)
    res = hub.http_api("patch", url, indexconfig)
    index_show(hub, indexname)

def index_delete(hub, indexname):
    url = hub.get_index_url(indexname, slash=False)
    hub.http_api("delete", url, None)

def index_list(hub, indexname):
    url = hub.get_user_url() + "/"
    res = hub.http_api("get", url, None)
    for name in res["result"]:
        hub.info(name)

def get_indexconfig_reply(hub, indexname, ok404=False):
    """ return 2-tuple of index url and indexconfig
    or None if configuration query failed. """
    url = hub.get_index_url(indexname, slash=False)
    res = hub.http_api("get", url, None, quiet=True)
    status = res["status"]
    if status == 200:
        if res["type"] != "indexconfig":
            hub.fatal("%s: wrong result type: %s" % (url, res["type"]))
        return res["result"]
    elif status == 404 and ok404:
        return None
    hub.fatal("%s: got return code %s for getting json"
                %(indexname, res["status"]))

def index_show(hub, indexname):
    ixconfig = get_indexconfig_reply(hub, indexname, ok404=False)
    hub.info(indexname + ":")
    hub.line("  type=%s" % ixconfig["type"])
    hub.line("  bases=%s" % ",".join(ixconfig["bases"]))
    hub.line("  volatile=%s" % (ixconfig["volatile"],))
    hub.line("  acl_upload=%s" % ",".join(ixconfig["acl_upload"]))

def main(hub, args):
    hub.requires_login()
    indexname = args.indexname
    kvdict = parse_keyvalue_spec_index(args.keyvalues)
    if args.list:
        return index_list(hub, indexname)
    if args.create:
        if not indexname:
            hub.fatal("need to specify index for creation")
        return index_create(hub, indexname, kvdict)
    if args.delete:
        if not indexname:
            hub.fatal("need to specify index for deletion")
        if kvdict:
            hub.fatal("cannot --delete if you specify key=values")
        return index_delete(hub, indexname)
    if not indexname:
        indexname = hub.current.index
    if kvdict:
        return index_modify(hub, indexname, kvdict)
    else:
        return index_show(hub, indexname)

def parse_keyvalue_spec_index(keyvalues):
    kvdict = parse_keyvalue_spec(keyvalues)
    if "acl_upload" in kvdict:
        kvdict["acl_upload"] = kvdict["acl_upload"].split(",")
    return kvdict
