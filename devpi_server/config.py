import sys
import optparse
from logging import getLogger

import py
from devpi_server.types import canraise
log = getLogger(__name__)

def addoptions(parser):
    group = parser.getgroup("main", "main options")
    group.addoption("--version", action="store_true",
            help="show devpi_version")

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

    group = parser.getgroup("upstream", "pypi upstream options")
    group.addoption("--pypiurl", metavar="url", type=str,
            default="https://pypi.python.org/",
            help="base url of remote pypi server")

    group.addoption("--refresh", type=float, metavar="SECS",
            default=60,
            help="periodically pull changes from pypi.python.org")

def parseoptions(argv):
    if argv is None:
        argv = sys.argv
    argv = map(str, argv)
    parser = Parser()
    addoptions(parser)
    options, args = parser.parse(argv[1:])
    config = Config(options)
    return config

class ConfigurationError(Exception):
    """ incorrect configuration or environment settings. """

@canraise(ConfigurationError)
def configure_redis_start(port):
    from pkg_resources import resource_string
    templatestring = resource_string("devpi_server.cfg",
                                     "redis.conf.template")
    redis_server = py.path.local.sysfind("redis-server")
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


class MyOptionParser(optparse.OptionParser):
    def __init__(self, parser):
        self._parser = parser
        optparse.OptionParser.__init__(self, usage=parser._usage,
                                       add_help_option=True)

class Parser:
    """ Parser for command line arguments. """

    def __init__(self, usage=None, processopt=None):
        self._anonymous = OptionGroup("custom options", parser=self)
        self._groups = []
        self._processopt = processopt
        self._usage = usage

    def processoption(self, option):
        if self._processopt:
            if option.dest:
                self._processopt(option)

    def getgroup(self, name, description="", after=None):
        """ get (or create) a named option Group.

        :name: name of the option group.
        :description: long description for --help output.
        :after: name of other group, used for ordering --help output.

        The returned group object has an ``addoption`` method with the same
        signature as :py:func:`parser.addoption
        <_pytest.config.Parser.addoption>` but will be shown in the
        respective group in the output of ``pytest. --help``.
        """
        for group in self._groups:
            if group.name == name:
                return group
        group = OptionGroup(name, description, parser=self)
        i = 0
        for i, grp in enumerate(self._groups):
            if grp.name == after:
                break
        self._groups.insert(i+1, group)
        return group

    def addoption(self, *opts, **attrs):
        """ register a command line option.

        :opts: option names, can be short or long options.
        :attrs: same attributes which the ``add_option()`` function of the
           `optparse library
           <http://docs.python.org/library/optparse.html#module-optparse>`_
           accepts.

        After command line parsing options are available on the pytest config
        object via ``config.option.NAME`` where ``NAME`` is usually set
        by passing a ``dest`` attribute, for example
        ``addoption("--long", dest="NAME", ...)``.
        """
        self._anonymous.addoption(*opts, **attrs)

    def parse(self, args):
        self.optparser = optparser = MyOptionParser(self)
        groups = self._groups + [self._anonymous]
        for group in groups:
            if group.options:
                desc = group.description or group.name
                optgroup = optparse.OptionGroup(optparser, desc)
                optgroup.add_options(group.options)
                optparser.add_option_group(optgroup)
        return self.optparser.parse_args([str(x) for x in args])


class OptionGroup:
    def __init__(self, name, description="", parser=None):
        self.name = name
        self.description = description
        self.options = []
        self.parser = parser

    def addoption(self, *optnames, **attrs):
        """ add an option to this group. """
        #if "default" in attrs and attrs.get("action") == "store":
        if attrs.get("action") != "store_true":
            attrs["help"] += " [%s]" % attrs["default"]
        option = optparse.Option(*optnames, **attrs)
        self._addoption_instance(option, shortupper=False)

    def _addoption(self, *optnames, **attrs):
        option = optparse.Option(*optnames, **attrs)
        self._addoption_instance(option, shortupper=True)

    def _addoption_instance(self, option, shortupper=False):
        if not shortupper:
            for opt in option._short_opts:
                if opt[0] == '-' and opt[1].islower():
                    raise ValueError("lowercase shortoptions reserved")
        if self.parser:
            self.parser.processoption(option)
        self.options.append(option)

