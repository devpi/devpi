from .filestore import FileEntry
from .main import CommandRunner
from .main import Fatal
from .main import xom_from_config
import sys
import time


def add_fsck_options(parser, pluginmanager):
    parser.addoption(
        "--checksum", action="store_true", default=True, dest="checksum",
        help="Perform checksum validation.")
    parser.addoption(
        "--no-checksum", action="store_false", dest="checksum",
        help="Skip checksum validation.")


def fsck():
    """ devpi-fsck command line entry point. """
    with CommandRunner() as runner:
        pluginmanager = runner.pluginmanager
        parser = runner.create_parser(
            description="Run a file consistency check of the devpi-server database.",
            add_help=False)
        parser.add_help_option()
        parser.add_configfile_option()
        parser.add_logging_options()
        parser.add_storage_options()
        add_fsck_options(parser.addgroup("fsck options"), pluginmanager)
        config = runner.get_config(sys.argv, parser=parser)
        runner.configure_logging(config.args)
        xom = xom_from_config(config)
        args = xom.config.args
        log = xom.log
        log.info("serverdir: %s", xom.config.server_path)
        log.info("uuid: %s", xom.config.nodeinfo["uuid"])
        keyfs = xom.keyfs
        keys = (keyfs.get_key('PYPIFILE_NOMD5'), keyfs.get_key('STAGEFILE'))
        last_time = time.time()
        processed = 0
        missing_files = 0
        got_errors = False
        with xom.keyfs.read_transaction() as tx:
            log.info("Checking at serial %s" % tx.at_serial)
            relpaths = tx.iter_relpaths_at(keys, tx.at_serial)
            for item in relpaths:
                if item.value is None:
                    continue
                if time.time() - last_time > 5:
                    last_time = time.time()
                    log.info(
                        "Processed a total of %s files (serial %s/%s) so far."
                        % (processed, tx.at_serial - item.serial, tx.at_serial))
                processed = processed + 1
                key = keyfs.get_key_instance(item.keyname, item.relpath)
                entry = FileEntry(key, item.value)
                if not entry.last_modified:
                    continue
                if not entry.file_exists():
                    missing_files += 1
                    if missing_files < 10:
                        got_errors = True
                        log.error("Missing file %s" % entry.relpath)
                    elif missing_files == 10:
                        log.error("Further missing files will be omitted.")
                    continue
                if not args.checksum:
                    continue
                msg = entry.validate()
                if msg is not None:
                    got_errors = True
                    log.error("%s - %s", entry.relpath, msg)
            log.info(
                "Finished with a total of %s files."
                % processed)
            if missing_files:
                log.error(
                    "A total of %s files are missing."
                    % missing_files)
            if got_errors:
                msg = "There have been errors during consistency check."
                raise Fatal(msg)
    return runner.return_code
