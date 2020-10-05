import json


def main(hub, args=None):
    hub.set_quiet()
    current = hub.current
    args = hub.args

    path = args.path

    current = hub.current

    if path.startswith(('http://', 'https://')):
        url = path
    elif path[0] != "/" and not current.index:
        hub.fatal("cannot use relative path without an active index")
    elif current.index:
        url = current.index_url.addpath(path)
    elif current.root_url:
        url = current.root_url.addpath(path)
    else:
        hub.fatal("no server currently selected")
    r = hub.http_api("get", url, quiet=True, check_version=False)
    if hub.args.verbose:
        hub.line("GET REQUEST sent to %s" % url)
        for name in sorted(r.headers):
            hub.line("%s: %s" %(name.upper(), r.headers[name]))
        hub.line()
    hub.out_json(r._json)
    return


def main_patchjson(hub, args=None):
    hub.set_quiet()
    current = hub.current
    args = hub.args

    path = args.path
    with open(args.jsonfile, "r") as f:
        data = json.load(f)

    current = hub.current

    if path[0] != "/" and not current.index:
        hub.fatal("cannot use relative path without an active index")
    url = current.index_url.addpath(path)
    r = hub.http_api("patch", url, kvdict=data, quiet=True, check_version=False)
    hub.line("PATCH REQUEST sent to %s" % url.url)
    hub.out_json(r._json)
    return
