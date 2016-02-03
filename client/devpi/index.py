from devpi.use import parse_keyvalue_spec

def index_create(hub, url, kvdict):
    hub.http_api("put", url, kvdict)
    index_show(hub, url)

def index_modify(hub, url, kvdict):
    reply = hub.http_api("get", url, type="indexconfig")
    for name, val in kvdict.items():
        reply.result[name] = val
        hub.info("%s changing %s: %s" %(url.path, name, val))

    hub.http_api("patch", url, reply.result)
    index_show(hub, url)

def index_delete(hub, url):
    hub.info("About to remove: %s" % url)
    if hub.ask_confirm("Are you sure"):
        hub.http_api("delete", url, None)
        hub.info("index deleted: %s" % url)

def index_list(hub, indexname):
    url = hub.current.get_user_url()
    res = hub.http_api("get", url.url, None)
    name = res.result['username']
    for index in res.result.get('indexes', {}):
        hub.info("%s/%s" % (name, index))

def index_show(hub, url):
    if not url:
        hub.fatal("no index specified and no index in use")
    reply = hub.http_api("get", url, None, quiet=True, type="indexconfig")
    ixconfig = reply.result
    hub.info(url.url + ":")
    key_order = ["type", "bases", "volatile", "acl_upload"]
    additional_keys = set(ixconfig) - set(key_order)
    additional_keys = additional_keys - set(('projects',))
    key_order.extend(sorted(additional_keys))
    for key in key_order:
        if key not in ixconfig:
            continue
        value = ixconfig[key]
        if isinstance(value, list):
            value = ",".join(value)
        hub.line("  %s=%s" % (key, value))

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
    # XXX devpi-server 3.0.0 handles the splitting on it's own, this is for
    # compatibility with older devpi-server
    for key in ("acl_upload", "bases", "pypi_whitelist"):
        if key in kvdict:
            kvdict[key] = [x for x in kvdict[key].split(",") if x]
    return kvdict
