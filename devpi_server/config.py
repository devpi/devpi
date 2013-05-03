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

    opt = group.addoption("--datadir", type=str, metavar="DIR",
            default="~/.devpi/serverdata",
            help="data directory for devpi-server")

    group.addoption("--port",  type=int,
            default=3141,
            help="port to listen for http requests")

    group.addoption("--refresh", type=float, metavar="SECS",
            default=60,
            help="interval for consulting changelog api of pypi.python.org")


    group = parser.addgroup("deploy", "deployment options")
    group.addoption("--gendeploy", action="store", metavar="DIR",
            help="(unix only) generate a pre-configured self-contained "
                 "virtualenv directory which puts devpi-server and "
                 "redis-server under supervisor control.  Also provides "
                 "nginx/cron files to help with permanent deployment. ")

    group.addoption("--redismode", metavar="auto|manual",
            action="store", choices=("auto", "manual"),
            default="auto",
            help="whether to start redis as a sub process")

    group.addoption("--redisport", type=int, metavar="PORT",
            default=3142,
            help="redis server port number")

    group.addoption("--bottleserver", metavar="TYPE",
            default="wsgiref",
            help="bottle server class, you may try eventlet or others")

    group.addoption("--debug", action="store_true",
            help="run wsgi application with debug logging")


def parseoptions(argv, addoptions=addoptions):
    if argv is None:
        argv = sys.argv
    argv = map(str, argv)
    parser = MyArgumentParser(
        description="Start an index server acting as a cache for "
                    "pypi.python.org, suitable for pip/easy_install usage. "
                    "The server automatically refreshes the cache of all "
                    "indexes which have changed on the pypi.python.org side.")
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
        target = render(None, cwd, "redis-devpi.conf", redisdir=cwd,
                        redisport=port)
        return (".*ready to accept connections on port %s.*" % port,
                [str(redis_server), str(target)])
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

def gendeploycfg(config, venvdir, tw=None):
    """ generate etc/ structure with supervisord.conf for running
    devpi-server and redis under supervisor control. """
    if tw is None:
        tw = py.io.TerminalWriter()
        tw.cwd = py.path.local()

    tw.line("creating etc/ directory for supervisor configuration", bold=True)
    etc = venvdir.ensure("etc", dir=1)
    httpport = config.args.port
    redisport = config.args.redisport
    datadir = venvdir.ensure("data", dir=1)
    redisdir = datadir.ensure("redis", dir=1)
    logdir = venvdir.ensure("log", dir=1)

    render(tw, etc, "supervisord.conf", venvdir=venvdir,
           devpiport=httpport, redisport=redisport,
           logdir=logdir, datadir=datadir)
    render(tw, etc, "redis-devpi.conf", redisdir=redisdir, redisport=redisport)
    nginxconf = render(tw, etc, "nginx-devpi.conf", format=1, port=httpport,
                       datadir=datadir)
    indexurl = "http://localhost:%s/ext/pypi/simple/" % httpport
    devpictl = create_devpictl(tw, venvdir, redisport, httpport)
    cron = create_crontab(tw, etc, devpictl)
    tw.line("created and configured %s" % venvdir, bold=True)
    tw.line(py.std.textwrap.dedent("""\
    You may now execute the following:

         alias devpi-ctl='%(devpictl)s'

    and then call:

        devpi-ctl start all

    after which you can configure pip to always use the running index server:

        # content of $USER/.pip/pip.conf
        [global]
        index-url = %(indexurl)s

    %(cron)s
    As a bonus, we have prepared an nginx config at:

        %(nginxconf)s

    which you might modify and copy to your /etc/nginx/sites-enabled
    directory.
    """) % locals())
    tw.line("may quick pypi installations be with you :)", bold=True)

def create_crontab(tw, etc, devpictl):
    crontab = py.path.local.sysfind("crontab")
    if crontab is None:
        return ""
    oldcrontab = crontab.sysexec("-l")
    for line in oldcrontab.split("\n"):
        if line.strip()[:1] != "#" and "devpi-ctl" in line:
            return ""
    newcrontab = (oldcrontab.rstrip() + "\n" +
                  "@reboot %s start all\n" % devpictl)
    crontabpath = etc.join("crontab")
    crontabpath.write(newcrontab)
    tw.line("wrote %s" % crontabpath, bold=True)
    return py.std.textwrap.dedent("""\
        It seems you are using "cron", so we created a new copy of
        your new user-crontab which starts devpi-server at boot. With:

            crontab %s

        you should be able to install the new crontab but please check it
        first.
    """ % crontabpath)



def create_devpictl(tw, tmpdir, redisport, httpport):
    devpiserver = tmpdir.join("bin", "devpi-server")
    if not devpiserver.check():
        tw.line("created fake devpictl", red=True)
        return tmpdir.join("bin", "devpi-ctl")
    firstline = devpiserver.readlines(cr=0)[0]

    devpictlpy = py.path.local(__file__).dirpath("ctl.py").read()
    devpictl = render(tw, devpiserver.dirpath(), "devpi-ctl",
                      firstline=firstline, redisport=redisport,
                      httpport=httpport, devpictlpy=devpictlpy)
    tw.line("wrote %s" % devpictl, bold=True)
    s = py.std.stat
    setmode = s.S_IXUSR # | s.S_IXGRP | s.S_IXOTH
    devpictl.chmod(devpictl.stat().mode | setmode)
    return devpictl


def render(tw, basedir, confname, format=None, **kw):
    template = confname + ".template"
    from pkg_resources import resource_string
    templatestring = resource_string("devpi_server.cfg", template)

    kw = dict([(x[0],str(x[1])) for x in kw.items()])
    if format is None:
        result = templatestring.format(**kw)
    else:
        result = templatestring % kw
    conf = basedir.join(confname)
    conf.write(result)
    if tw is not None:
        tw.line("wrote %s" % conf, bold=True)
    return conf
