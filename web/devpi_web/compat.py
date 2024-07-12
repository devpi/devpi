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
