""" a WSGI server to serve PyPI compatible indexes and a full
recursive cache of pypi.python.org packages.
"""

import argparse
import os, sys
import py

class ConvertAddr(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        parts = values.rsplit(":", 1)
        if len(parts) < 2:
            parts.append(3141)
        else:
            if not parts[0]:
                parts[0] = "localhost"
            if not parts[1]:
                parts[1] = 3141
            else:
                parts[1] = int(parts[1])
        setattr(namespace, self.dest, tuple(parts))

def parse_args(argv):
    argv = map(str, argv)
    parser = argparse.ArgumentParser(prog=argv[0])

    parser.add_argument("--addr", metavar="address", type=str, dest="addr",
        default=("localhost", 3141), action=ConvertAddr,
        help="host:port specification, examples: ':5000', '1.2.3.4:6000'",
    )

    parser.add_argument("--data", metavar="DIR", type=str, dest="datadir",
        default="~/.devpi/data",
        help="data directory, where database and packages are stored",
    )
    return parser.parse_args(argv[1:])

def main(argv=None):
    if argv is None:
        argv = sys.argv
    args = parse_args(argv)
    print args
