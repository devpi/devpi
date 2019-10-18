from devpi_server.config import MyArgumentParser
from devpi_server.config import add_configfile_option
from devpi_server.config import add_help_option
from devpi_server.config import add_storage_options
from devpi_server.config import parseoptions, get_pluginmanager
from devpi_server.log import configure_cli_logging
from devpi_server.main import Fatal
from devpi_server.main import xom_from_config
from devpi_web.config import add_indexer_backend_option
from devpi_web.main import get_indexer
import py
import sys


def clear_index(argv=None):
    if argv is None:
        argv = sys.argv
    else:
        # for tests
        argv = [str(x) for x in argv]
    pluginmanager = get_pluginmanager()
    try:
        parser = MyArgumentParser(
            description="Clear project search index.",
            add_help=False)
        add_help_option(parser, pluginmanager)
        add_configfile_option(parser, pluginmanager)
        add_storage_options(parser, pluginmanager)
        add_indexer_backend_option(parser, pluginmanager)
        config = parseoptions(pluginmanager, argv, parser=parser)
        configure_cli_logging(config.args)
        xom = xom_from_config(config)
        log = xom.log
        log.warn("You should stop devpi-server before running this command.")
        ix = get_indexer(xom)
        ix.delete_index()
        log.info("Index deleted, start devpi-server again to let the index rebuild automatically.")
    except Fatal as e:
        tw = py.io.TerminalWriter(sys.stderr)
        tw.line("fatal: %s" % e.args[0], red=True)
        return 1
