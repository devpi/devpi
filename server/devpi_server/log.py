from ruamel import yaml
import threading
import logging
import logging.config
import contextlib
import json
import sys


threadlocal = threading.local()


def configure_logging(config_args):
    # clear handlers so that a second call to configure_logging
    # reconfigures properly
    logging.getLogger('').handlers = []

    if config_args.debug:
        loglevel = logging.DEBUG
    else:
        loglevel = logging.INFO
    logging.basicConfig(
        level=loglevel,
        format='%(asctime)s %(levelname)-5.5s %(message)s',
        stream=sys.stdout)
    requests_log = logging.getLogger("requests.packages.urllib3")
    requests_log.setLevel(logging.ERROR)

    if config_args.logger_cfg:
        with open(config_args.logger_cfg, 'rt') as f:
            if config_args.logger_cfg.endswith(".json"):
                logger_cfg = json.loads(f.read())
            else:
                logger_cfg = yaml.YAML(typ='safe', pure=True).load(f.read())
        logging.config.dictConfig(logger_cfg)


def configure_cli_logging(config_args):
    logging.basicConfig(
        level=logging.INFO,
        format='%(levelname)-5.5s %(message)s',
        stream=sys.stderr)
    requests_log = logging.getLogger("requests.packages.urllib3")
    requests_log.setLevel(logging.ERROR)


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
        self._logout.debug(self._prefix + msg, *args)

    def info(self, msg, *args):
        self._logout.info(self._prefix + msg, *args)

    def warn(self, msg, *args):
        self._logout.warning(self._prefix + msg, *args)

    def error(self, msg, *args):
        self._logout.error(self._prefix + msg, *args)

    def exception(self, msg, *args):
        self._logout.exception(self._prefix + msg, *args)


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
