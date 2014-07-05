import sys
import py
from devpi_server.keyfs import KeyFS
import argparse
import pprint

def garbage_collect_analysis(keyfs):
    key2revisions = {}
    for serial in range(keyfs.get_next_serial()):
        changelog = keyfs._fs.get_changes(serial)
        for key, (keyname, back_serial, value) in changelog.items():
            l = key2revisions.setdefault(key, [])
            l.append(serial)
    l = sorted(key2revisions.items(), key=lambda x: len(x[1]))
    for key, revlist in l:
        if len(revlist) >= 2:
            tw.line("%s: %s" % (key, revlist))

if __name__ == "__main__":
    tw = py.io.TerminalWriter()
    parser = argparse.ArgumentParser()
    parser.add_argument("--serverdir",  type=str,
            default="~/.devpi/server",
            help="serverdir directory to look at")
    parser.add_argument("--gc",  action="store_true",
            help="garbage collect analysis")
    parser.add_argument("changelog", type=int,
            help="changelog to look at", nargs="*")
    args = parser.parse_args()
    basedir = py.path.local(args.serverdir, expanduser=True)
    assert basedir.exists()
    keyfs = KeyFS(basedir)
    tw.line("keyfs at %s" % basedir, bold=True)
    if args.gc:
        garbage_collect_analysis(keyfs)
    elif args.changelog:
        for serial in args.changelog:
            tw.sep("-", "serial %s" % serial)
            pprint.pprint(keyfs._fs.get_changes(int(serial)))
    else:
        tw.line("number of changelogs: %s" % keyfs.get_next_serial())

