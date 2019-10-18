from devpi_web import hookspecs
from pluggy import PluginManager


def get_pluginmanager(config, load_entry_points=True):
    # lookup cached value
    pm = getattr(config, 'devpiweb_pluginmanager', None)
    if pm is not None:
        return pm
    pm = PluginManager("devpiweb")
    # support old plugins, but emit deprecation warnings
    pm._implprefix = "devpiweb_"
    pm.add_hookspecs(hookspecs)
    if load_entry_points:
        pm.load_setuptools_entrypoints("devpi_web")
    pm.check_pending()
    # cache the expensive setup
    config.devpiweb_pluginmanager = pm
    return pm


def add_indexer_backend_option(parser, pluginmanager=None):
    parser.addoption(
        "--indexer-backend", type=str, metavar="NAME", default="whoosh",
        action="store",
        help="the indexer backend to use")
