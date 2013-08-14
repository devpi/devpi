import sys
import types
from devpi_server.main import *

def test_get_bottle_server(monkeypatch):
    assert get_bottle_server("wsgiref") == "wsgiref"
    assert get_bottle_server("eventlet") == "eventlet"
    monkeypatch.setitem(sys.modules, "eventlet", None)
    assert get_bottle_server("auto") == "wsgiref"

def test_get_bottle_server_eventlet_if_exists(monkeypatch):
    mod = types.ModuleType("eventlet")
    monkeypatch.setitem(sys.modules, "eventlet", mod)
    assert get_bottle_server("auto") == "eventlet"
