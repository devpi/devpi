from devpi_server.keyfs import loads
from functools import partial
from pprint import pformat
from pyramid.view import view_config


@view_config(
    route_name="keyfs",
    request_method="GET",
    renderer="templates/keyfs.pt")
def keyfs_view(request):
    fs = request.registry['xom'].keyfs._fs
    conn = fs.get_sqlconn()
    query = request.params.get('query')
    serials = []
    if query:
        bquery = query.encode('ascii')
        q = "SELECT serial, data FROM changelog"
        for serial, data in conn.execute(q):
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
    fs = request.registry['xom'].keyfs._fs
    serial = request.matchdict['serial']
    query = request.params.get('query')
    data = fs.get_raw_changelog_entry(serial)
    (changes, rel_renames) = loads(data)
    return dict(
        changes=changes,
        rel_renames=rel_renames,
        pformat=partial(pformat, width=180),
        serial=serial,
        query=query)
