try:
    from devpi_server.config import DevpiArgumentParser
except ImportError:
    from devpi_server.config import MyArgumentParser as DevpiArgumentParser

try:
    from devpi_server import thread as devpithread
except ImportError:
    from devpi_server import mythread as devpithread

try:
    import tomllib
except ImportError:
    import tomli as tomllib


__all__ = [
    "DevpiArgumentParser",
    "devpithread",
    "tomllib",
]
