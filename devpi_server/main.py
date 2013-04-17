""" a WSGI server to serve PyPI compatible indexes and a full
recursive cache of pypi.python.org packages.
"""

import os, sys
import py
from devpi_server.plugin import hookimpl

def main(argv=None):
    from devpi_server.plugin import PluginManager
    from devpi_server import hookspec
    pm = PluginManager(hookspec)
    for plugin in ("main", "extpypi", "wsgi"):
        pm.import_plugin("devpi_server." + plugin)
    if argv is None:
        argv = sys.argv
    config = pm.hook.server_cmdline_parse(pm=pm, argv=argv)
    return pm.hook.server_cmdline_main(config=config)

@hookimpl()
def server_cmdline_parse(pm, argv):
    import argparse
    argv = map(str, argv)
    parser = argparse.ArgumentParser(prog=argv[0])
    pm.hook.server_addoptions(parser=parser)
    args = parser.parse_args(argv[1:])
    config = Config(pm, args)
    return config

class Config:
    def __init__(self, pm, args):
        self.pm = pm
        self.args = args
        self.hook = pm.hook

@hookimpl()
def server_addoptions(parser):
    parser.add_argument("--datadir", type=str, metavar="DIR",
            default="~/.devpi/httpcachedata",
            help="data directory for httpcache")

    parser.add_argument("--redisport", type=int, metavar="PORT",
            default=6379,
            help="redis server port number")

@hookimpl()
def resource_redis(config):
    import redis
    return redis.StrictRedis(port=config.args.redisport)

@hookimpl(tryfirst=True)
def server_cmdline_main(config):
    #config.hook.server_configure(config=config)
    #try:
    return config.hook.server_mainloop(config=config)
    #finally:
    #    config.hook.server_unconfigure(config=config)



