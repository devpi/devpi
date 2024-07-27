from .main import CommandRunner
from .main import Fatal
from .main import xom_from_config
from .model import run_passwd
import sys


def get_username():
    return input("User to set password for: ")


def passwd():
    """ devpi-passwd command line entry point. """
    with CommandRunner() as runner:
        parser = runner.create_parser(
            description="Change password for a user directly in "
                        "devpi-server database.",
            add_help=False)
        parser.add_help_option()
        parser.add_configfile_option()
        parser.add_logging_options()
        parser.add_storage_options()
        parser.add_argument("user", nargs='?')
        config = runner.get_config(sys.argv, parser)
        runner.configure_logging(config.args)
        xom = xom_from_config(config)
        log = xom.log
        log.info("serverdir: %s", xom.config.server_path)
        log.info("uuid: %s", xom.config.nodeinfo["uuid"])
        username = xom.config.args.user
        if username is None:
            username = get_username()
        if not username:
            raise Fatal("No user name provided.")
        with xom.keyfs.write_transaction():
            return run_passwd(xom.model, username)
