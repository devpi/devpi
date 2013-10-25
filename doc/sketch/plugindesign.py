"""
sketch on a plugin that deals with tox-ini parsing

devpi_test

"""

from devpi.test import pluginhook

@pluginhook()
def add_options(parser):
    parser.add_argument("--toxini", ...)

@pluginhook()
def get_tox_ini(hub, unpack_path):
    if hub.args.toxini:
        return hub.get_existing_file(hub.args.toxini)
    p = path.join("tox.ini")
    if p.exists():
        return p
    if hub.args.fallback_ini:
        return hub.get_existing_file(hub.args.fallback_ini)
    hub.fatal("no tox.ini found in %s, no fallback/toxini defined on commandline"
              % unpack_path))


