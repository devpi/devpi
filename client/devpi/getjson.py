from devpi_common.url import URL
import json


def main(hub, args=None):
    hub.set_quiet()
    current = hub.current
    args = hub.args

    path_url = URL(args.path)

    current = hub.current

    if path_url.scheme in ('http', 'https'):
        url = path_url
    elif not path_url.path.startswith("/") and not current.index:
        hub.fatal("cannot use relative path without an active index")
    elif current.index:
        url = current.index_url.addpath(path_url.path)
    elif current.root_url:
        url = current.root_url.addpath(path_url.path)
    else:
        hub.fatal("no server currently selected")
    if path_url.query:
        url = url.replace(query=path_url.query)
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
