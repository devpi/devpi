import os
import sys
import py
import json

from devpi import log
from devpi.use import parse_keyvalue_spec
from devpi.util import url as urlutil

DEFAULT_BASES = ["root/dev", ]

def index_create(hub, indexname, kvdict):
    url = hub.current.get_index_url(indexname, slash=False)
    hub.http_api("put", url, kvdict)
    index_show(hub, indexname)

def index_modify(hub, indexname, kvdict):
    indexconfig = get_indexconfig_reply(hub, indexname, ok404=False)
    for name, val in kvdict.items():
        indexconfig[name] = val
        hub.info("%s changing %s: %s" %(indexname, name, val))

    url = hub.current.get_index_url(indexname, slash=False)
    res = hub.http_api("patch", url, indexconfig)
    index_show(hub, indexname)

def index_delete(hub, indexname):
    url = hub.current.get_index_url(indexname, slash=False)
    hub.http_api("delete", url, None)

def index_list(hub, indexname):
    url = hub.current.get_user_url(hub.current.auth[0]) + "/"
    res = hub.http_api("get", url, None)
    for name in res["result"]:
        hub.info(name)

def get_indexconfig_reply(hub, indexname, ok404=False):
    """ return 2-tuple of index url and indexconfig
    or None if configuration query failed. """
    url = hub.current.get_index_url(indexname, slash=False)
    res = hub.http_api("get", url, None, quiet=True)
    if res.status_code == 200:
        if res["type"] != "indexconfig":
            hub.fatal("%s: wrong result type: %s" % (url, res["type"]))
        return res["result"]
    elif res.status_code == 404 and ok404:
        return None
    hub.fatal("%s: trying to get json resulted in: %s %s"
                %(indexname, res.status_code, res.reason))

def index_show(hub, indexname):
    ixconfig = get_indexconfig_reply(hub, indexname, ok404=False)
    hub.info(indexname + ":")
    hub.line("  type=%s" % ixconfig["type"])
    hub.line("  bases=%s" % ",".join(ixconfig["bases"]))
    hub.line("  volatile=%s" % (ixconfig["volatile"],))
    hub.line("  uploadtrigger_jenkins=%s" %(
                ixconfig["uploadtrigger_jenkins"],))
    hub.line("  acl_upload=%s" % ",".join(ixconfig["acl_upload"]))

def main(hub, args):
    hub.requires_login()
    indexname = args.indexname
    if args.delete:
        if not indexname:
            hub.fatal("need to specify index for deletion")
        if arg.keyvalues:
            hub.fatal("cannot --delete if you specify key=values")
        return index_delete(hub, indexname)

    keyvalues = list(args.keyvalues)
    if args.create:
        if not indexname:
            hub.fatal("need to specify index for creation")
        kvdict = parse_keyvalue_spec_index(hub, keyvalues)
        return index_create(hub, indexname, kvdict)

    if indexname and "=" in indexname:
        keyvalues.append(indexname)
        indexname = hub.current.index
    if not indexname:
        indexname = hub.current.index
    kvdict = parse_keyvalue_spec_index(hub, keyvalues)
    if args.list:
        return index_list(hub, indexname)
    if kvdict:
        return index_modify(hub, indexname, kvdict)
    else:
        return index_show(hub, indexname)

def parse_keyvalue_spec_index(hub, keyvalues):
    try:
        kvdict = parse_keyvalue_spec(keyvalues)
    except ValueError:
        hub.fatal("arguments must be format NAME=VALUE: %r" %( keyvalues,))
    if "acl_upload" in kvdict:
        kvdict["acl_upload"] = kvdict["acl_upload"].split(",")
    return kvdict
