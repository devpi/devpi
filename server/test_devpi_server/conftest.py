import warnings


pytest_plugins = ["test_devpi_server.plugin"]


def __getattr__(name):
    from . import plugin
    if name in dir(plugin):
        warnings.warn(
            'Import from test_devpi_server.conftest is deprecated and will break with 7.x. '
            'Use \'pytest_plugins = ["test_devpi_server.plugin"]\' instead.',
            DeprecationWarning,
            stacklevel=2)
        return getattr(plugin, name)
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)
