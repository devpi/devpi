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


def read_transaction(keyfs):
    if hasattr(keyfs, 'read_transaction'):
        return keyfs.read_transaction()
    return keyfs.transaction(write=False)


def write_transaction(keyfs):
    if hasattr(keyfs, 'write_transaction'):
        return keyfs.write_transaction()
    return keyfs.transaction(write=True)
