from .main import CommandRunner
from .main import DATABASE_VERSION
from .main import Fatal
from .main import init_default_indexes
from .main import set_state_version
from .main import xom_from_config
import sys


def init(pluginmanager=None, argv=None):
    """ devpi-init command line entry point. """
    if argv is None:
        argv = sys.argv
    else:
        # for tests
        argv = [str(x) for x in argv]
    with CommandRunner(pluginmanager=pluginmanager) as runner:
        parser = runner.create_parser(
            description="Initialize new devpi-server instance.",
            add_help=False)
        parser.add_help_option()
        parser.add_configfile_option()
        parser.add_logging_options()
        parser.add_role_option()
        parser.add_primary_url_option()
        parser.add_storage_options()
        parser.add_init_options()
        config = runner.get_config(argv, parser=parser)
        runner.configure_logging(config.args)
        if config.nodeinfo_path.exists():
            msg = f"The path {config.server_path!r} already contains devpi-server data."
            raise Fatal(msg)
        sdir = config.server_path
        if not (sdir.exists() and len(list(sdir.iterdir())) >= 2):
            set_state_version(config, DATABASE_VERSION)
        xom = xom_from_config(config, init=True)
        init_default_indexes(xom)
    return runner.return_code or 0
