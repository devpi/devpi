try:
    from devpi_server.filestore import get_hashes

    def get_default_hash_spec(content_or_file):
        return get_hashes(content_or_file).get_default_spec()
except ImportError:
    from devpi_server.filestore import get_default_hash_spec  # noqa: F401


try:
    from devpi_server.main import Fatal

    def fatal(msg, *, exc=None):
        raise Fatal(msg) from exc
except ImportError:
    from devpi_server.main import fatal  # noqa: F401


try:
    from test_devpi_server.plugin import make_file_url
except ImportError:
    from test_devpi_server.conftest import make_file_url  # noqa: F401


def get_entry_hash_spec(entry):
    return (
        entry.best_available_hash_spec
        if hasattr(entry, 'best_available_hash_spec') else
        entry.hash_spec)


def get_entry_hash_value(entry):
    return (
        entry.best_available_hash_value
        if hasattr(entry, 'best_available_hash_value') else
        entry.hash_value)
