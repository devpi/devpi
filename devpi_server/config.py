import sys
from logging import getLogger
import argparse

import py
from devpi_server.types import canraise
import devpi_server
log = getLogger(__name__)

def addoptions(parser):
    group = parser.addgroup("main", "main options")
    group.addoption("--version", action="store_true",
            help="show devpi_version (%s)" % devpi_server.__version__)

    group.addoption("--datadir", type=str, metavar="DIR",
            default="~/.devpi/serverdata",
            help="data directory for devpi-server")

    group.addoption("--port",  type=int,
            default=3141,
            help="port to listen for http requests")

    group.addoption("--redisport", type=int, metavar="PORT",
            default=3142,
            help="redis server port number")

    group.addoption("--redismode", metavar="auto|manual",
            action="store", choices=("auto", "manual"),
            default="auto",
            help="whether to start redis as a sub process")

    group.addoption("--bottleserver", metavar="TYPE",
            default="wsgiref",
            help="bottle server class, you may try eventlet or others")

    group.addoption("--debug", action="store_true",
            help="run wsgi application with debug logging")

    group = parser.addgroup("upstream", "pypi upstream options")
    group.addoption("--pypiurl", metavar="url", type=str,
            default="https://pypi.python.org/",
            help="base url of remote pypi server. "
                 "WARNING: changing this to a pypi server that "
                 "does not support the changelog xmlrpc API "
                 "will make devpi-server serve the first "
                 "cached view. ")

    group.addoption("--refresh", type=float, metavar="SECS",
            default=60,
            help="periodically pull changes from pypi.python.org")


def parseoptions(argv, addoptions=addoptions):
    if argv is None:
        argv = sys.argv
    argv = map(str, argv)
    parser = MyArgumentParser()
    addoptions(parser)
    args = parser.parse_args(argv[1:])
    config = Config(args)
    return config

class MyArgumentParser(argparse.ArgumentParser):
    def __init__(self, *args, **kwargs):
        if "defaultget" in kwargs:
            self._defaultget = kwargs.pop("defaultget")
        else:
            self._defaultget = {}.__getitem__
        super(MyArgumentParser, self).__init__(*args, **kwargs)

    def addoption(self, *args, **kwargs):
        opt = super(MyArgumentParser, self).add_argument(*args, **kwargs)
        self._processopt(opt)
        return opt

    def _processopt(self, opt):
        try:
            opt.default = self._defaultget(opt.dest)
        except KeyError:
            pass
        if opt.help and opt.default:
            opt.help += " [%s]" % opt.default

    def addgroup(self, *args, **kwargs):
        grp = super(MyArgumentParser, self).add_argument_group(*args, **kwargs)
        def group_addoption(*args2, **kwargs2):
            opt = grp.add_argument(*args2, **kwargs2)
            self._processopt(opt)
            return opt
        grp.addoption = group_addoption
        return grp


class ConfigurationError(Exception):
    """ incorrect configuration or environment settings. """

@canraise(ConfigurationError)
def configure_redis_start(port):
    from pkg_resources import resource_string
    templatestring = resource_string("devpi_server.cfg",
                                     "redis.conf.template")
    redis_server = py.path.local.sysfind("redis-server")
    if redis_server is None:
        if sys.platform == "win32":
            redis_server = py.path.local.sysfind("redis-server",
                    paths= [r"c:\\Program Files\redis"])
        if redis_server is None:
            raise ConfigurationError("'redis-server' binary not found in PATH")
    def prepare_redis(cwd):
        content = templatestring.format(libredis=cwd,
                          daemonize="no",
                          port=port, pidfile=cwd.join("_pid_from_redis"))
        target = cwd.join("redis.conf")
        target.write(content)
        log.debug("wrote redis configuration at %s", target)
        return (".*ready to accept connections on port %s.*" % port,
                [str(redis_server), "redis.conf"])
    return prepare_redis

class Config:
    def __init__(self, args):
        self.args = args

