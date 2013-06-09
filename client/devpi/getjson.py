import os
import sys
import py

import json

from devpi import log, cached_property
from devpi.util import url as urlutil
import posixpath

def main(hub, args=None):
    current = hub.current
    args = hub.args

    path = args.path
    if path:
        if path[0] != "/":
            if not current.index:
                hub.fatal("cannot use relative path without an active index")
            url = urlutil.joinpath(hub.get_index_url(), path)
        else:
            url = urlutil.joinpath(current.rooturl, path)
        data = hub.http_api("get", url, quiet=True)
        hub.out_json(data)
        return

