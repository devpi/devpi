""" a WSGI server to serve PyPI compatible indexes and a full
recursive cache of pypi.python.org packages.
"""

import eventlet
import os, sys
import py
from devpi_server.plugin import hookimpl

def main(argv=None):
    eventlet.monkey_patch()
    xom = preparexom(argv)
    return xom.hook.server_cmdline_main(xom=xom)

def preparexom(argv):
    from devpi_server.plugin import PluginManager
    from devpi_server import hookspec
    pm = PluginManager(hookspec)
    for plugin in ("main", "extpypi", "wsgi"):
        pm.import_plugin("devpi_server." + plugin)
    if argv is None:
        argv = sys.argv
    config = pm.hook.server_cmdline_parse(pm=pm, argv=argv)
    return XOM(pm, config)

@hookimpl()
def server_cmdline_parse(pm, argv):
    import argparse
    argv = map(str, argv)
    parser = argparse.ArgumentParser(prog=argv[0])
    pm.hook.server_addoptions(parser=parser)
    args = parser.parse_args(argv[1:])
    config = Config(args)
    return config

class Config:
    def __init__(self, args):
        self.args = args

class XOM:
    def __init__(self, pm, config):
        self.pm = pm
        self.hook = pm.hook
        self.config = config
        self._spawned = []

    def kill_spawned(self):
        for x in self._spawned:
            x.kill()

    def spawn(self, func):
        return eventlet.spawn(func)

    def sleep(self, secs):
        eventlet.sleep(secs)


@hookimpl()
def server_addoptions(parser):
    parser.add_argument("--datadir", type=str, metavar="DIR",
            default="~/.devpi/httpcachedata",
            help="data directory for httpcache")

    parser.add_argument("--redisport", type=int, metavar="PORT",
            default=6379,
            help="redis server port number")

@hookimpl()
def resource_redis(xom):
    import redis
    return redis.StrictRedis(port=xom.config.args.redisport)

@hookimpl(tryfirst=True)
def server_cmdline_main(xom):
    #config.hook.server_configure(config=config)
    #try:
    return xom.hook.server_mainloop(xom=xom)
    #finally:
    #    config.hook.server_unconfigure(config=config)



