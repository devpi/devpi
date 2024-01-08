from devpi.use import get_keyvalues


def index_create(hub, url, kvdict):
    hub.http_api("put", url, kvdict)
    no_projects_url = url.replace(query=dict(no_projects=""))
    index_show(hub, no_projects_url)


def index_modify(hub, url, keyvalues):
    features = hub.current.features or set()
    no_projects_url = url.replace(query=dict(no_projects=""))
    reply = hub.http_api("get", no_projects_url, type="indexconfig")
    if 'server-keyvalue-parsing' in features:
        # the server supports key value parsing
        patch = keyvalues
        for op in keyvalues:
            hub.info("%s %s" % (url.path, op))
    else:
        patch = reply.result
        try:
            kvdict = keyvalues.kvdict
        except ValueError as e:
            hub.fatal(e)
        for name, val in sorted(kvdict.items()):
            patch[name] = val
            hub.info("%s changing %s: %s" %(url.path, name, val))

    hub.http_api("patch", url, patch)
    index_show(hub, no_projects_url)


def index_delete(hub, url):
    hub.info("About to remove: %s" % url)
    if hub.ask_confirm("Are you sure"):
        hub.http_api("delete", url, None)
        hub.info("index deleted: %s" % url)


def index_list(hub, username):
    try:
        url = hub.current.get_user_url(username)
    except ValueError as e:
        hub.fatal(e)
    res = hub.http_api("get", url.url, None)
    name = res.result['username']
    for index in sorted(res.result.get('indexes', {})):
        hub.info("%s/%s" % (name, index))


def index_show(hub, url):
    if not url:
        hub.fatal("no index specified and no index in use")
    reply = hub.http_api(
        "get", url, fatal=False, quiet=True, type="indexconfig")
    if reply.status_code == 403:
        hub.requires_login()
    elif reply.status_code >= 400:
        raise SystemExit(1)
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
        # indexname is actually a keyvalue, since it comes before the remaining
        # keyvalues we insert it in first place
        keyvalues.insert(0, indexname)
        indexname = None
    keyvalues = get_keyvalues_index(hub, keyvalues)
    return indexname, keyvalues


def main(hub, args):
    indexname, keyvalues = parse_posargs(hub, args)

    if args.list:
        return index_list(hub, indexname)

    url = hub.current.get_index_url(indexname, slash=False)

    if (args.delete or args.create) and not indexname:
        hub.fatal("need to explicitly specify index for deletion/creation")
    if args.delete:
        if args.keyvalues:
            hub.fatal("cannot delete if you specify key=values")
        hub.requires_login()
        return index_delete(hub, url)
    if args.create:
        hub.requires_login()
        return index_create(hub, url, keyvalues.kvdict)
    if keyvalues:
        hub.requires_login()
        return index_modify(hub, url, keyvalues)
    else:
        if args.no_projects:
            url = url.replace(query=dict(no_projects=""))
        return index_show(hub, url)


def get_keyvalues_index(hub, keyvalues):
    try:
        return get_keyvalues(keyvalues)
    except ValueError:
        hub.fatal("arguments must be format NAME=VALUE: %r" % (keyvalues,))
