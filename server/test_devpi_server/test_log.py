
import pytest
import logging
from devpi_server.log import *


@pytest.fixture
def taglogger(caplog):
    return TagLogger(logging.getLogger())


@pytest.mark.parametrize("level", ["debug", "info", "warn", "error"])
class TestTagLogger:

    def test_basic(self, taglogger, caplog, level):
        getattr(taglogger, level)("hello")
        rec = caplog.getrecords()
        assert len(rec) == 1

    def test_new(self, taglogger, caplog, level):
        log = taglogger.new("[hello]")
        getattr(log, level)("world")
        rec = caplog.getrecords()
        assert len(rec) == 1
        assert rec[0].msg == "[hello] world"

def test_taglogger_prefix(caplog):
    log = TagLogger(logging.getLogger(), prefix="hello")
    log.info("this")

    assert caplog.getrecords("hello this")

def test_taglogger_exception(taglogger, caplog):
    try:
        0/0
    except Exception:
        taglogger.exception("this")
    assert caplog.getrecords()[0].exc_info

def test_taglogger_push(caplog):
    log = thread_push_log("hello")
    log.info("42")
    assert caplog.records()[0].msg == "hello 42"

    log = thread_push_log("world")
    log.info("17")
    assert caplog.records()[1].msg == "hello world 17"
    thread_pop_log()
    log = thread_current_log()
    log.info("10")
    assert caplog.records()[2].msg == "hello 10"

def test_taglogger_default(caplog):
    log = TagLogger(prefix="hello")
    log.info("this")
    assert caplog.records()[0].msg == "hello this"

def test_taglogger_wrong_prefix(caplog):
    thread_push_log("hello")
    with pytest.raises(ValueError):
        thread_pop_log("this")

def test_taglogger_context_empty(caplog):
    log = thread_current_log()
    log.info("hello")
    assert caplog.records()[0].msg == "NOCTX hello"

def test_threadlog(caplog):
    threadlog.info("hello")
    assert caplog.records()[0].msg == "NOCTX hello"
    thread_push_log("this")
    threadlog.info("hello")
    assert caplog.records()[1].msg == "this hello"

def test_threadlog_around(caplog):
    with threadlog.around("info", "hello") as log:
        log.info("inner")
    recs = caplog.records()
    assert len(recs) == 3
    assert recs[0].msg == "NOCTX hello"
    assert recs[1].msg == "NOCTX inner"
    assert recs[2].msg == "NOCTX FIN: hello"

