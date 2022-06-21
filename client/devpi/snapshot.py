def main(hub, args):
    current = hub.require_valid_current_with_index()
    source_index = current.indexname
    target_index = args.target
    if "/" in target_index:
        hub.fatal("'/' not allowed in target index ; snapshot only allowed within one user indices")
    url = current.root_url.joinpath("+snapshot", source_index)
    url_authed = current.add_auth_to_url(url)
    r = hub.http.post(url_authed, json={"target_index": target_index})
    if r.status_code != 200:
        hub.fatal("Couldn't snapshot %s via %s: %s %s" % (
            source_index, url, r.status_code, r.reason))
    hub.info(f"{source_index} successfully snapshoted into {target_index}")
