try:
    from devpi_server.main import Fatal

    def fatal(msg, *, exc=None):
        raise Fatal(msg) from exc
except ImportError:
    from devpi_server.main import fatal  # noqa: F401


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
