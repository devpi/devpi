from __future__ import annotations

from devpi_server.fileutil import loads
from difflib import SequenceMatcher
from functools import singledispatch
from itertools import chain
from pyramid.httpexceptions import HTTPForbidden
from pyramid.view import view_config
from typing import TYPE_CHECKING
import json


if TYPE_CHECKING:
    from typing import Any


@singledispatch
def pformat(val: Any) -> str:
    msg = f"don't know how to handle type {type(val)!r}"
    raise TypeError(msg)


@pformat.register
def _(val: None) -> str:  # noqa: ARG001
    return "<deleted>"


@pformat.register
def _(val: object) -> str:
    return json.dumps(val, indent=4, default=sorted, sort_keys=True)


@view_config(
    route_name="keyfs",
    request_method="GET",
    renderer="templates/keyfs.pt")
def keyfs_view(request):
    xom = request.registry['xom']
    if not xom.config.args.debug_keyfs:
        raise HTTPForbidden("+keyfs views disabled")
    storage = xom.keyfs._storage
    query = request.params.get('query')
    serials = []
    if query:
        bquery = query.encode('ascii')
        q = "SELECT serial, data FROM changelog"
        with storage.get_connection() as conn:
            for serial, data in conn._sqlconn.execute(q):
                if bquery in data:
                    serials.append(serial)
    else:
        with storage.get_connection() as conn:
            start = range(min(5, conn.last_changelog_serial + 1))
            end = range(max(0, conn.last_changelog_serial - 4), conn.last_changelog_serial + 1)
            serials.extend(sorted(set(chain(start, end))))
    return dict(
        query=query,
        serials=serials)


def diff(prev, current):
    prev_lines = prev.splitlines()
    lines = current.splitlines()
    cruncher = SequenceMatcher(None, prev_lines, lines)
    result = []
    for tag, alo, ahi, blo, bhi in cruncher.get_opcodes():
        if tag == 'equal':
            for i in range(alo, ahi):
                result.append(('equal', prev_lines[i]))
        elif tag == 'delete':
            for i in range(alo, ahi):
                result.append(('remove', prev_lines[i]))
        elif tag == 'insert':
            for i in range(blo, bhi):
                result.append(('insert', lines[i]))
        elif tag == 'replace':
            for i in range(alo, ahi):
                result.append(('remove', prev_lines[i]))
            for i in range(blo, bhi):
                result.append(('insert', lines[i]))
    return result


@view_config(
    route_name="keyfs_changelog",
    request_method="GET",
    renderer="templates/keyfs_changelog.pt")
def keyfs_changelog_view(request):
    xom = request.registry['xom']
    if not xom.config.args.debug_keyfs:
        raise HTTPForbidden("+keyfs views disabled")
    storage = xom.keyfs._storage
    serial = request.matchdict['serial']
    query = request.params.get('query')
    with storage.get_connection() as conn:
        data = conn.get_raw_changelog_entry(serial)
        last_changelog_serial = conn.last_changelog_serial
        (changes, rel_renames) = loads(data)
        for k, v in list(changes.items()):
            prev_formatted = ''
            if v[1] >= 0:
                prev_data = conn.get_raw_changelog_entry(v[1])
                prev_changes = loads(prev_data)[0]
                for prev_k, prev_v in sorted(prev_changes.items()):
                    if prev_k == k and prev_v[0] == v[0]:
                        prev_formatted = pformat(prev_v[2])
            formatted = pformat(v[2])
            diffed = diff(prev_formatted, formatted)
            (_, latest_serial) = conn.db_read_typedkey(k)
            changes[k] = dict(
                type=v[0],
                previous_serial=v[1],
                latest_serial=latest_serial,
                diffed=diffed)
    return dict(
        changes=changes,
        rel_renames=rel_renames,
        pformat=pformat,
        last_changelog_serial=last_changelog_serial,
        serial=int(serial),
        query=query)
