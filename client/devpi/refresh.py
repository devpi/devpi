def main(hub, args):
    current = hub.require_valid_current_with_index()
    for pkg in args.pkgnames:
        url = current.index_url.addpath('+simple/%s/refresh' % pkg).url
        r = hub.http.post(url)
        if r.status_code != 200:
            hub.error("Couldn't refresh %s via %s: %s %s" % (
                pkg, url, r.status_code, r.reason))
        hub.info("Refreshed %s" % pkg)
