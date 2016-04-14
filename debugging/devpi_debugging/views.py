from devpi_server.fileutil import loads
from functools import partial
from pprint import pformat
from pyramid.view import view_config


@view_config(
    route_name="keyfs",
    request_method="GET",
    renderer="templates/keyfs.pt")
def keyfs_view(request):
    storage = request.registry['xom'].keyfs._storage
    query = request.params.get('query')
    serials = []
    if query:
        bquery = query.encode('ascii')
        q = "SELECT serial, data FROM changelog"
        with storage.get_connection() as conn:
            for serial, data in conn._sqlconn.execute(q):
                if bquery in data:
                    serials.append(serial)
    return dict(
        query=query,
        serials=serials)


@view_config(
    route_name="keyfs_changelog",
    request_method="GET",
    renderer="templates/keyfs_changelog.pt")
def keyfs_changelog_view(request):
    storage = request.registry['xom'].keyfs._storage
    serial = request.matchdict['serial']
    query = request.params.get('query')
    with storage.get_connection() as conn:
        data = conn.get_raw_changelog_entry(serial)
    (changes, rel_renames) = loads(data)
    return dict(
        changes=changes,
        rel_renames=rel_renames,
        pformat=partial(pformat, width=180),
        serial=serial,
        query=query)
