import sys
import os.path
from logging import getLogger, basicConfig
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

    group = parser.addgroup("upstream", "pypi upstream options")
    group.addoption("--pypiurl", metavar="url", type=str,
            default="https://pypi.python.org/",
            help="base url of remote pypi server. "
                 "WARNING: changing this to a pypi server that "
                 "does not support the changelog xmlrpc API "
                 "will make devpi-server serve the first "
                 "cached view forever. ")

    group.addoption("--refresh", type=float, metavar="SECS",
            default=60,
            help="periodically pull changes from pypi.python.org")

    group = parser.addgroup("deploy", "deployment options")
    group.addoption("--gendeploy", action="store_true",
            help="generate a etc/ directory suitable for running devpi-server "
                 "and redis-server under supervisord control (unix only). "
                 "also creates a etc/nginx-devpi.conf which you may edit and "
                 "copy into something like /etc/nginx/sites-enabled/")

    group.addoption("--redismode", metavar="auto|manual",
            action="store", choices=("auto", "manual"),
            default="auto",
            help="whether to start redis as a sub process")

    group.addoption("--bottleserver", metavar="TYPE",
            default="wsgiref",
            help="bottle server class, you may try eventlet or others")

    group.addoption("--debug", action="store_true",
            help="run wsgi application with debug logging")



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
    redis_server = py.path.local.sysfind("redis-server")
    if redis_server is None:
        if sys.platform == "win32":
            redis_server = py.path.local.sysfind("redis-server",
                    paths= [r"c:\\Program Files\redis"])
        if redis_server is None:
            raise ConfigurationError("'redis-server' binary not found in PATH")
    def prepare_redis(cwd):
        target = render(None, cwd, "redis-devpi.conf", libredis=cwd, port=port)
        return (".*ready to accept connections on port %s.*" % port,
                [str(redis_server), "redis.conf"])
    return prepare_redis

class Config:
    def __init__(self, args):
        self.args = args

def configure_logging(config):
    if config.args.debug:
        loglevel = "DEBUG"
    else:
        loglevel = "INFO"
    basicConfig(level=loglevel,
                format='%(asctime)s [%(levelname)-5.5s] %(name)s: %(message)s')

def getpath(path):
    return py.path.local(os.path.expanduser(str(path)))

def gendeploy(config, etc, redis=None, logdir=None, tw=None):
    """ generate etc/ structure with supervisord.conf for running
    devpi-server and redis under supervisor control. """
    if tw is None:
        tw = py.io.TerminalWriter()
        tw.cwd = py.path.local()
    httpport = config.args.port
    redisport = httpport + 1
    supervisorport = httpport - 1

    tw.line("creating etc/ directory for supervisor configuration", bold=True)
    datadir = getpath(config.args.datadir)
    redisdir = datadir.ensure("redis", dir=1)
    logdir = datadir.ensure("log", dir=1)
    render(tw, etc, "supervisord.conf", port=supervisorport,
           devpiport=str(httpport),
           redisport=str(redisport),
           logdir=logdir,
           datadir=getpath(config.args.datadir))
    render(tw, etc, "redis-devpi.conf", libredis=redisdir, port=redisport)
    render(tw, etc, "nginx-devpi.conf", format=1, port=str(httpport),
           datadir=config.args.datadir)
    tw.line(py.std.textwrap.dedent("""\
    You may now run 'pip install supervisor' and then 'supervisord' which
    should pick up etc/supervisord.conf automatically and start a
    redis-server and devpi-server process.  'supervisorctl status'
    should show you two running processes.

    As a bonus, etc/nginx-devpi.conf also contains a sample configuration
    which you could modify and put into a directory
    like /etc/nginx/sites-enabled/ to serve on a proper url.

    And don't forget that you can also set the environment variable
    PIP_INDEX_URL to your server at
    http://localhost:%(httpport)s/ext/pypi/simple/
    """ % locals()))
    tw.line("may quick pypi installations be with you :)", bold=True)


def render(tw, basedir, confname, format=None, **kw):
    template = confname + ".template"
    from pkg_resources import resource_string
    templatestring = resource_string("devpi_server.cfg", template)
    if format is None:
        result = templatestring.format(**kw)
    else:
        result = templatestring % kw
    conf = basedir.join(confname)
    conf.write(result)
    if tw is not None:
        tw.line("wrote %s" % conf.relto(tw.cwd), bold=True)
    return conf
