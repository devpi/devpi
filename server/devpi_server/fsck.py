from .filestore import FileEntry
from .log import configure_cli_logging
from .main import CommandRunner
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
        parser.add_storage_options()
        add_fsck_options(parser.addgroup("fsck options"), pluginmanager)
        config = runner.get_config(sys.argv, parser=parser)
        configure_cli_logging(config.args)
        xom = xom_from_config(config)
        args = xom.config.args
        log = xom.log
        log.info("serverdir: %s" % xom.config.serverdir)
        log.info("uuid: %s" % xom.config.nodeinfo["uuid"])
        keyfs = xom.keyfs
        keys = (keyfs.get_key('PYPIFILE_NOMD5'), keyfs.get_key('STAGEFILE'))
        last_time = time.time()
        processed = 0
        missing_files = 0
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
                        log.error("Missing file %s" % entry.relpath)
                    elif missing_files == 10:
                        log.error("Further missing files will be omitted.")
                    continue
                if not args.checksum:
                    continue
                checksum = entry.file_get_checksum(entry.hash_type)
                if entry.hash_value != checksum:
                    log.error(
                        "%s - %s mismatch, got %s, expected %s"
                        % (entry.relpath, entry.hash_type, checksum, entry.hash_value))
            log.info(
                "Finished with a total of %s files."
                % processed)
            if missing_files:
                log.error(
                    "A total of %s files are missing."
                    % missing_files)
    return runner.return_code
