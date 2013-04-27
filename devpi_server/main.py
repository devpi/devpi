""" a WSGI server to serve PyPI compatible indexes and a full
recursive cache of pypi.python.org packages.
"""

import os, sys
import py
from devpi_server.plugin import hookimpl
import threading
from logging import getLogger
log = getLogger(__name__)

def main(argv=None):
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
    class Exiting(SystemExit):
        pass

    def __init__(self, pm, config):
        self.pm = pm
        self.hook = pm.hook
        self.config = config
        self._spawned = []
        self._shutdown = threading.Event()

    def shutdown(self):
        self._shutdown.set()

    def sleep(self, secs):
        if self._shutdown.wait(secs):
            raise self.Exiting()

    def spawn(self, func, args=(), kwargs={}):
        def logging_spawn():
            self._spawned.append(thread)
            log.debug("execution starts %s %s %s", func, args, kwargs)
            try:
                log.debug("calling")
                func(*args, **kwargs)
            except self.Exiting:
                log.debug("received Exiting signal")
            finally:
                log.debug("execution finished %s", func)
            self._spawned.remove(thread)

        thread = threading.Thread(target=logging_spawn)
        thread.setDaemon(True)
        thread.start()
        return thread


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
    return xom.hook.server_mainloop(xom=xom)
