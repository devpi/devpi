from __future__ import annotations

from ruamel import yaml
from typing import TYPE_CHECKING
import contextlib
import json
import logging
import logging.config
import sys
import threading


if TYPE_CHECKING:
    import argparse


threadlocal = threading.local()


def _configure_logging(config_args: argparse.Namespace) -> None:
    logging.basicConfig(
        level=(
            logging.DEBUG
            if getattr(config_args, "debug", False) else
            logging.INFO),
        format='%(asctime)s %(levelname)-5.5s %(message)s',
        stream=sys.stdout)
    requests_log = logging.getLogger("requests.packages.urllib3")
    requests_log.setLevel(logging.ERROR)
    httpx_log = logging.getLogger("httpx")
    httpx_log.setLevel(logging.ERROR)
    httpcore_log = logging.getLogger("httpcore")
    httpcore_log.setLevel(logging.ERROR)

    logger_cfg_fn = getattr(config_args, "logger_cfg", None)
    if logger_cfg_fn:
        with open(logger_cfg_fn) as f:
            if logger_cfg_fn.endswith(".json"):
                logger_cfg = json.loads(f.read())
            else:
                logger_cfg = yaml.YAML(typ='safe', pure=True).load(f.read())
        logging.config.dictConfig(logger_cfg)


def configure_logging(config_args: argparse.Namespace) -> None:
    # clear handlers so that a second call to configure_logging
    # reconfigures properly
    logging.getLogger('').handlers.clear()
    _configure_logging(config_args)


def configure_cli_logging(config_args):
    _configure_logging(config_args)


class TagLogger:
    def __init__(self, logout=None, prefix='', last=None):
        if logout is None:
            logout = logging.getLogger('')
        self._logout = logout
        if prefix:
            prefix = prefix.rstrip() + " "
        self._prefix = prefix
        self.last = last

    def new(self, tag):
        return self.__class__(self._logout, prefix=self._prefix + tag + " ",
                              last=self)

    def debug(self, msg, *args):
        self._logout.debug(self._prefix + msg, *args, stacklevel=2)

    def info(self, msg, *args):
        self._logout.info(self._prefix + msg, *args, stacklevel=2)

    def warning(self, msg, *args):
        self._logout.warning(self._prefix + msg, *args, stacklevel=2)

    warn = warning

    def error(self, msg, *args):
        self._logout.error(self._prefix + msg, *args, stacklevel=2)

    def exception(self, msg, *args):
        self._logout.exception(self._prefix + msg, *args, stacklevel=2)


class ThreadLog:
    def __getattr__(self, name):
        return getattr(_thread_current_log(), name)

    @contextlib.contextmanager
    def around(self, level, msg, *args):
        tlog = _thread_current_log()
        log = getattr(tlog, level)
        log(msg, *args)
        try:
            yield tlog
        finally:
            log("FIN: " + msg, *args)


threadlog = ThreadLog()


def thread_push_log(prefix):
    oldtlog = getattr(threadlocal, "taglogger", None)
    if oldtlog is None:
        tlog = TagLogger(logging.getLogger(), prefix=prefix)
    else:
        tlog = threadlocal.taglogger.new(prefix)
    threadlocal.taglogger = tlog
    return tlog


def thread_pop_log(prefix):
    if not threadlocal.taglogger._prefix.rstrip().endswith(prefix):
        raise ValueError("Wrong thread log order, expected %r, saw %r" %
                         (prefix, threadlocal.taglogger._prefix))
    threadlocal.taglogger = threadlocal.taglogger.last


def thread_change_log_prefix(prefix, old_prefix):
    if old_prefix and not threadlocal.taglogger._prefix.rstrip().endswith(old_prefix):
        raise ValueError("Wrong thread log order, expected %r, saw %r" %
                         (old_prefix, threadlocal.taglogger._prefix))
    threadlocal.taglogger._prefix = prefix.rstrip() + " "


def thread_clear_log():
    try:
        del threadlocal.taglogger
    except AttributeError:
        pass


def _thread_current_log():
    taglogger = getattr(threadlocal, "taglogger", None)
    if taglogger is None:
        taglogger = TagLogger(prefix="NOCTX")
    return taglogger
