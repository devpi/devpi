import sys
import py
from devpi_server.keyfs import KeyFS
import argparse
import pprint

if __name__ == "__main__":
    tw = py.io.TerminalWriter()
    parser = argparse.ArgumentParser()
    parser.add_argument("--serverdir",  type=str,
            default="~/.devpi/server",
            help="serverdir directory to look at")
    parser.add_argument("changelog",  type=int, default=None,
            help="changelog to look at", nargs="?")
    args = parser.parse_args()
    basedir = py.path.local(args.serverdir, expanduser=True)
    assert basedir.exists()
    keyfs = KeyFS(basedir)
    tw.line("keyfs at %s" % basedir, bold=True)
    if args.changelog is not None:
        pprint.pprint(keyfs._fs.get_changes(args.changelog))
    else:
        tw.line("number of changelogs: %s" % keyfs.get_next_serial())

