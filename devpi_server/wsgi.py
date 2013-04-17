import argparse

from devpi_server.plugin import hookimpl

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

@hookimpl()
def server_addoptions(parser):
    parser.add_argument("--addr", metavar="address", type=str, dest="addr",
        default=("localhost", 3141), action=ConvertAddr,
        help="host:port specification, examples: ':5000', '1.2.3.4:6000'",
    )


