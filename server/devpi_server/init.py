from .config import MyArgumentParser
from .config import add_configfile_option
from .config import add_help_option
from .config import add_init_options
from .config import add_master_url_option
from .config import add_role_option
from .config import add_storage_options
from .config import parseoptions, get_pluginmanager
from .log import configure_cli_logging
from .main import DATABASE_VERSION
from .main import Fatal
from .main import fatal
from .main import init_default_indexes
from .main import set_state_version
from .main import xom_from_config
import py
import sys


def init(pluginmanager=None, argv=None):
    """ devpi-init command line entry point. """
    if argv is None:
        argv = sys.argv
    else:
        # for tests
        argv = [str(x) for x in argv]
    if pluginmanager is None:
        pluginmanager = get_pluginmanager()
    try:
        parser = MyArgumentParser(
            description="Initialize new devpi-server instance.",
            add_help=False)
        add_help_option(parser, pluginmanager)
        add_configfile_option(parser, pluginmanager)
        add_role_option(parser, pluginmanager)
        add_master_url_option(parser, pluginmanager)
        add_storage_options(parser, pluginmanager)
        add_init_options(parser, pluginmanager)
        config = parseoptions(pluginmanager, argv, parser=parser)
        configure_cli_logging(config.args)
        if config.path_nodeinfo.exists():
            fatal("The path '%s' already contains devpi-server data." % config.serverdir)
        sdir = config.serverdir
        if not (sdir.exists() and len(sdir.listdir()) >= 2):
            set_state_version(config, DATABASE_VERSION)
        xom = xom_from_config(config, init=True)
        init_default_indexes(xom)
        return 0
    except Fatal as e:
        tw = py.io.TerminalWriter(sys.stderr)
        tw.line("fatal: %s" % e.args[0], red=True)
        return 1
