import sys
import os.path
from logging import getLogger, basicConfig
import argparse

import py
from devpi_server.types import canraise, cached_property
import devpi_server
log = getLogger(__name__)

def addoptions(parser):
    group = parser.addgroup("main", "main options")
    group.addoption("--version", action="store_true",
            help="show devpi_version (%s)" % devpi_server.__version__)

    opt = group.addoption("--datadir", type=str, metavar="DIR",
            default="~/.devpi/server",
            help="directory for server data")

    group.addoption("--port",  type=int,
            default=3141,
            help="port to listen for http requests.  When used with "
                 "--gendeploy, port+1 will be used to prevent "
                 "accidental clashes with ad-hoc runs.")

    group.addoption("--host",  type=str,
            default="localhost",
            help="domain/ip address to listen on")

    group.addoption("--outside-url",  type=str, dest="outside_url",
            metavar="URL",
            default=None,
            help="the outside URL where this server will be reachable. "
                 "Set this if you proxy devpi-server through a web server "
                 "and the web server does not set or you want to override "
                 "the custom X-outside-url header.")

    group.addoption("--refresh", type=float, metavar="SECS",
            default=60,
            help="interval for consulting changelog api of pypi.python.org")

    group.addoption("--passwd", action="store", metavar="USER",
            help="set password for user USER (interactive)")
    group = parser.addgroup("deploy", "deployment options")
    group.addoption("--gendeploy", action="store", metavar="DIR",
            help="(unix only) generate a pre-configured self-contained "
                 "virtualenv directory which puts devpi-server "
                 "under supervisor control.  Also provides "
                 "nginx/cron files to help with permanent deployment. ")

    group.addoption("--secretfile", type=str, metavar="path",
            default="~/.devpi/server/.secret",
            help="file containing the server side secret used for user "
                 "validation. If it does not exist, a random secret "
                 "is generated on start up and used subsequently. ")

    group.addoption("--bottleserver", metavar="TYPE",
            default="wsgiref",
            help="bottle server class, you may try eventlet or others")

    group.addoption("--debug", action="store_true",
            help="run wsgi application with debug logging")

def try_argcomplete(parser):
    try:
        import argcomplete
    except ImportError:
        pass
    else:
        argcomplete.autocomplete(parser)

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
    try_argcomplete(parser)
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


class Config:
    def __init__(self, args):
        self.args = args
        self.secretfile = py.path.local(os.path.expanduser(args.secretfile))

    @cached_property
    def secret(self):
        if not self.secretfile.check():
            self.secretfile.dirpath().ensure(dir=1)
            self.secretfile.write(os.urandom(32).encode("base64"))
            s = py.std.stat
            self.secretfile.chmod(s.S_IRUSR|s.S_IWUSR)
        return self.secretfile.read()

def configure_logging(config):
    if config.args.debug:
        loglevel = "DEBUG"
    else:
        loglevel = "INFO"
    basicConfig(level=loglevel,
                format='%(asctime)s [%(levelname)-5.5s] %(name)s: %(message)s')

def getpath(path):
    return py.path.local(os.path.expanduser(str(path)))

def render(tw, basedir, confname, format=None, **kw):
    result = render_string(confname, format=format, **kw)
    conf = basedir.join(confname)
    conf.write(result)
    if tw is not None:
        tw.line("wrote %s" % conf, bold=True)
    return conf

def render_string(confname, format=None, **kw):
    template = confname + ".template"
    from pkg_resources import resource_string
    templatestring = resource_string("devpi_server.cfg", template)

    kw = dict([(x[0],str(x[1])) for x in kw.items()])
    if format is None:
        result = templatestring.format(**kw)
    else:
        result = templatestring % kw
    return result
