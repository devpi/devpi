def main(hub, args):
    current = hub.require_valid_current_with_index()
    if args.index and args.index.count("/") > 1:
        hub.fatal("index %r not of form USER/NAME or NAME" % args.index)
    for pkg in args.pkgnames:
        url = current.get_simpleproject_url(
            pkg, indexname=args.index).addpath('refresh').url
        r = hub.http.post(url)
        if r.status_code != 200:
            hub.error("Couldn't refresh %s via %s: %s %s" % (
                pkg, url, r.status_code, r.reason))
        hub.info("Refreshed %s" % pkg)
