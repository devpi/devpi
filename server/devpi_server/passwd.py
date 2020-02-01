from .config import MyArgumentParser
from .config import add_configfile_option
from .config import add_help_option
from .config import add_storage_options
from .config import parseoptions, get_pluginmanager
from .log import configure_cli_logging
from .main import Fatal
from .main import fatal
from .main import xom_from_config
from .model import run_passwd
import py
import sys


def get_username():
    msg = "User to set password for: "
    try:
        return raw_input(msg)
    except NameError:
        return input(msg)


def passwd():
    """ devpi-passwd command line entry point. """
    pluginmanager = get_pluginmanager()
    try:
        parser = MyArgumentParser(
            description="Change password for a user directly in "
                        "devpi-server database.",
            add_help=False)
        add_help_option(parser, pluginmanager)
        add_configfile_option(parser, pluginmanager)
        add_storage_options(parser, pluginmanager)
        parser.add_argument("user", nargs='?')
        config = parseoptions(pluginmanager, sys.argv, parser=parser)
        configure_cli_logging(config.args)
        xom = xom_from_config(config)
        log = xom.log
        log.info("serverdir: %s" % xom.config.serverdir)
        log.info("uuid: %s" % xom.config.nodeinfo["uuid"])
        username = xom.config.args.user
        if username is None:
            username = get_username()
        if not username:
            fatal("No user name provided.")
        with xom.keyfs.transaction(write=True):
            return run_passwd(xom.model, username)
    except Fatal as e:
        tw = py.io.TerminalWriter(sys.stderr)
        tw.line("fatal: %s" % e.args[0], red=True)
        return 1
