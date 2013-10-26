from devpi.use import parse_keyvalue_spec

def index_create(hub, url, kvdict):
    hub.http_api("put", url, kvdict)
    index_show(hub, url)

def index_modify(hub, url, kvdict):
    reply = hub.http_api("get", url, "indexconfig")
    for name, val in kvdict.items():
        reply.result[name] = val
        hub.info("%s changing %s: %s" %(url.path, name, val))

    hub.http_api("patch", url, reply.result)
    index_show(hub, url)

def index_delete(hub, url):
    hub.http_api("delete", url, None)
    hub.info("index deleted: %s" % url)

def index_list(hub, indexname):
    url = hub.current.get_user_url().asdir()
    res = hub.http_api("get", url, None)
    for name in res.result:
        hub.info(name)

def index_show(hub, url):
    if not url:
        hub.fatal("no index specified and no index in use")
    reply = hub.http_api("get", url, None, quiet=True, type="indexconfig")
    ixconfig = reply.result
    hub.info(url.url + ":")
    hub.line("  type=%s" % ixconfig["type"])
    hub.line("  bases=%s" % ",".join(ixconfig["bases"]))
    hub.line("  volatile=%s" % (ixconfig["volatile"],))
    hub.line("  uploadtrigger_jenkins=%s" %(
                ixconfig["uploadtrigger_jenkins"],))
    hub.line("  acl_upload=%s" % ",".join(ixconfig["acl_upload"]))

def parse_posargs(hub, args):
    indexname = args.indexname
    keyvalues = list(args.keyvalues)
    if indexname and "=" in indexname:
        keyvalues.append(indexname)
        indexname = None
    kvdict = parse_keyvalue_spec_index(hub, keyvalues)
    return indexname, kvdict

def main(hub, args):
    indexname, kvdict = parse_posargs(hub, args)

    if args.list:
        return index_list(hub, indexname)

    url = hub.current.get_index_url(indexname, slash=False)

    if (args.delete or args.create) and not indexname:
        hub.fatal("need to explicitly specify index for deletion/creation")
    if args.delete:
        if args.keyvalues:
            hub.fatal("cannot delete if you specify key=values")
        return index_delete(hub, url)
    if args.create:
        return index_create(hub, url, kvdict)
    if kvdict:
        return index_modify(hub, url, kvdict)
    else:
        return index_show(hub, url)

def parse_keyvalue_spec_index(hub, keyvalues):
    try:
        kvdict = parse_keyvalue_spec(keyvalues)
    except ValueError:
        hub.fatal("arguments must be format NAME=VALUE: %r" %( keyvalues,))
    if "acl_upload" in kvdict:
        kvdict["acl_upload"] = kvdict["acl_upload"].split(",")
    if "bases" in kvdict:
        kvdict["bases"] = [x for x in kvdict["bases"].split(",") if x]
    return kvdict
