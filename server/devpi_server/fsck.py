from .config import MyArgumentParser
from .config import add_configfile_option
from .config import add_help_option
from .config import add_storage_options
from .config import parseoptions, get_pluginmanager
from .filestore import FileEntry
from .log import configure_cli_logging
from .main import Fatal
from .main import check_python_version
from .main import xom_from_config
import py
import sys
import time


def fsck():
    """ devpi-fsck command line entry point. """
    check_python_version()
    pluginmanager = get_pluginmanager()
    try:
        parser = MyArgumentParser(
            description="Run a file consistency check of the devpi-server database.",
            add_help=False)
        add_help_option(parser, pluginmanager)
        add_configfile_option(parser, pluginmanager)
        add_storage_options(parser, pluginmanager)
        config = parseoptions(pluginmanager, sys.argv, parser=parser)
        configure_cli_logging(config.args)
        xom = xom_from_config(config)
        log = xom.log
        log.info("serverdir: %s" % xom.config.serverdir)
        log.info("uuid: %s" % xom.config.nodeinfo["uuid"])
        keyfs = xom.keyfs
        keys = (keyfs.get_key('PYPIFILE_NOMD5'), keyfs.get_key('STAGEFILE'))
        last_time = time.time()
        processed = 0
        with xom.keyfs.transaction(write=False) as tx:
            log.info("Checking at serial %s" % tx.at_serial)
            relpaths = tx.iter_relpaths_at(keys, tx.at_serial)
            for item in relpaths:
                if item.value is None:
                    continue
                if time.time() - last_time > 5:
                    last_time = time.time()
                    log.info(
                        "Processed a total of %s files so far."
                        % processed)
                processed = processed + 1
                key = keyfs.get_key_instance(item.keyname, item.relpath)
                entry = FileEntry(key, item.value)
                if not entry.last_modified:
                    continue
                checksum = entry.file_get_checksum(entry.hash_type)
                if entry.hash_value != checksum:
                    log.error(
                        "%s - %s mismatch, got %s, expected %s"
                        % (entry.relpath, entry.hash_type, checksum, entry.hash_value))
            log.info(
                "Processed a total of %s files."
                % processed)
    except Fatal as e:
        tw = py.io.TerminalWriter(sys.stderr)
        tw.line("fatal: %s" % e.args[0], red=True)
        return 1
