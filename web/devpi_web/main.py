from __future__ import unicode_literals
from chameleon.config import AUTO_RELOAD
from devpi_common.metadata import get_latest_version
from devpi_web import hookspecs
from devpi_web.doczip import remove_docs
from devpi_web.indexing import iter_projects, preprocess_project
from devpi_server.log import threadlog
from devpi_server.main import fatal
from pkg_resources import resource_filename
from pluggy import PluginManager, HookimplMarker
from pyramid.renderers import get_renderer
from pyramid_chameleon.renderer import ChameleonRendererLookup
import os
import sys


hookimpl = HookimplMarker("devpiweb")
devpiserver_hookimpl = HookimplMarker("devpiserver")


def theme_static_url(request, path):
    return request.static_url(
        os.path.join(request.registry['theme_path'], 'static', path))


def macros(request):
    # returns macros which may partially be overwritten in a theme
    result = {}
    paths = [
        resource_filename('devpi_web', 'templates/macros.pt'),
        "templates/macros.pt"]
    for path in paths:
        renderer = get_renderer(path)
        macros = renderer.implementation().macros
        for name in macros.names:
            if name in result:
                result['original-%s' % name] = result[name]
            result[name] = macros[name]
    return result


def navigation_version(context):
    version = context.version
    if version == 'latest':
        stage = context.model.getstage(context.username, context.index)
        version = stage.get_latest_version(context.project)
    elif version == 'stable':
        stage = context.model.getstage(context.username, context.index)
        version = stage.get_latest_version(context.project, stable=True)
    return version


def navigation_info(request):
    context = request.context
    path = [dict(
        url=request.route_url("root"),
        title="devpi")]
    result = dict(path=path)
    if context.matchdict and 'user' in context.matchdict:
        user = context.username
    else:
        return result
    if 'index' in context.matchdict:
        index = context.index
        path.append(dict(
            url=request.stage_url(user, index),
            title="%s/%s" % (user, index)))
    else:
        return result
    if 'project' in context.matchdict:
        name = context.project
        path.append(dict(
            url=request.route_url(
                "/{user}/{index}/{project}", user=user, index=index, project=name),
            title=name))
    else:
        return result
    if 'version' in context.matchdict:
        version = navigation_version(context)
        path.append(dict(
            url=request.route_url(
                "/{user}/{index}/{project}/{version}",
                user=user, index=index, project=name, version=version),
            title=version))
    else:
        return result
    return result


def status_info(request):
    msgs = []
    pm = request.registry['devpiweb-pluginmanager']
    for result in pm.hook.devpiweb_get_status_info(request=request):
        for msg in result:
            msgs.append(msg)
    states = set(x['status'] for x in msgs)
    if 'fatal' in states:
        status = 'fatal'
        short_msg = 'fatal'
    elif 'warn' in states:
        status = 'warn'
        short_msg = 'degraded'
    else:
        status = 'ok'
        short_msg = 'ok'
    url = request.route_url('/+status')
    return dict(status=status, short_msg=short_msg, msgs=msgs, url=url)


def query_docs_html(request):
    search_index = request.registry['search_index']
    return search_index.get_query_parser_html_help()


class ThemeChameleonRendererLookup(ChameleonRendererLookup):
    auto_reload = AUTO_RELOAD

    def __call__(self, info):
        # if the template exists in the theme, we will use it instead of the
        # original template
        theme_path = getattr(self, 'theme_path', None)
        if theme_path:
            theme_file = os.path.join(theme_path, info.name)
            if os.path.exists(theme_file):
                info.name = theme_file
        return ChameleonRendererLookup.__call__(self, info)


def get_pluginmanager(config, load_entry_points=True):
    pm = PluginManager("devpiweb")
    # support old plugins, but emit deprecation warnings
    pm._implprefix = "devpiweb_"
    pm.add_hookspecs(hookspecs)
    if load_entry_points:
        pm.load_setuptools_entrypoints("devpi_web")
    pm.check_pending()
    return pm


def includeme(config):
    from devpi_web import __version__
    from pyramid_chameleon.interfaces import IChameleonLookup
    from pyramid_chameleon.zpt import ZPTTemplateRenderer
    config.include('pyramid_chameleon')
    # we overwrite the template lookup to allow theming
    lookup = ThemeChameleonRendererLookup(ZPTTemplateRenderer, config.registry)
    config.registry.registerUtility(lookup, IChameleonLookup, name='.pt')
    config.add_static_view('+static-%s' % __version__, 'static')
    theme_path = config.registry['theme_path']
    if theme_path:
        # if a theme is used, we set the path on the lookup instance
        lookup.theme_path = theme_path
        # if a 'static' directory exists in the theme, we add it and a helper
        # method 'theme_static_url' on the request
        static_path = os.path.join(theme_path, 'static')
        if os.path.exists(static_path):
            config.add_static_view('+theme-static-%s' % __version__, static_path)
            config.add_request_method(theme_static_url)
    config.add_route('root', '/', accept='text/html')
    config.add_route('search', '/+search', accept='text/html')
    config.add_route('search_help', '/+searchhelp', accept='text/html')
    config.add_route(
        "docroot",
        "/{user}/{index}/{project}/{version}/+doc/{relpath:.*}")
    config.add_route(
        "docviewroot",
        "/{user}/{index}/{project}/{version}/+d/{relpath:.*}")
    config.add_route(
        "toxresults",
        "/{user}/{index}/{project}/{version}/+toxresults/{basename}")
    config.add_route(
        "toxresult",
        "/{user}/{index}/{project}/{version}/+toxresults/{basename}/{toxresult}")
    config.add_request_method(macros, reify=True)
    config.add_request_method(navigation_info, reify=True)
    config.add_request_method(status_info, reify=True)
    config.add_request_method(query_docs_html, reify=True)
    config.scan()


def get_indexer(config):
    pm = get_pluginmanager(config)
    indexers = {
        x['name']: x
        for x in pm.hook.devpiweb_indexer_backend()}
    (name, sep, setting_str) = config.args.indexer_backend.partition(':')
    settings = {}
    if setting_str:
        for item in setting_str.split(','):
            (key, value) = item.split('=', 1)
            settings[key] = value
    return indexers[name]['indexer'](config=config, settings=settings)


@devpiserver_hookimpl
def devpiserver_pyramid_configure(config, pyramid_config):
    # make the theme path absolute if it exists and make it available via the
    # pyramid registry
    theme_path = config.args.theme
    if theme_path:
        theme_path = os.path.abspath(theme_path)
        if not os.path.exists(theme_path):
            threadlog.error(
                "The theme path '%s' does not exist." % theme_path)
            sys.exit(1)
        if not os.path.isdir(theme_path):
            threadlog.error(
                "The theme path '%s' is not a directory." % theme_path)
            sys.exit(1)
    pyramid_config.registry['theme_path'] = theme_path
    # by using include, the package name doesn't need to be set explicitly
    # for registrations of static views etc
    pyramid_config.include('devpi_web.main')
    pyramid_config.registry['devpiweb-pluginmanager'] = get_pluginmanager(config)
    pyramid_config.registry['search_index'] = get_indexer(config)

    # monkeypatch mimetypes.guess_type on because pyramid-1.5.1/webob
    # choke on mimtypes.guess_type on windows with python2.7
    if sys.platform == "win32" and sys.version_info[:2] == (2, 7):
        import mimetypes
        old = mimetypes.guess_type

        def guess_type_str(url, strict=True):
            res = old(url, strict)
            return str(res[0]), res[1]

        mimetypes.guess_type = guess_type_str
        threadlog.debug("monkeypatched mimetypes.guess_type to return bytes")


@devpiserver_hookimpl
def devpiserver_add_parser_options(parser):
    web = None
    for action in parser._actions:
        if '--host' in action.option_strings:
            web = action.container
    web.addoption(
        "--theme", action="store",
        help="folder with template and resource overwrites for the web interface")
    indexing = parser.addgroup("search indexing")
    indexing.addoption(
        "--recreate-search-index", action="store_true",
        help="Recreate search index for all projects and their documentation. "
             "This is only needed if there where indexing related errors in a "
             "devpi-web release and you want to upgrade only devpi-web "
             "without a full devpi-server import/export. Requires "
             "--offline option.")
    indexing.addoption(
        "--indexer-backend", type=str, metavar="NAME", default="whoosh",
        action="store",
        help="the indexer backend to use")


@devpiserver_hookimpl
def devpiserver_mirror_initialnames(stage, projectnames):
    ix = get_indexer(stage.xom.config)
    ix.update_projects([preprocess_project(stage, name) for name in projectnames])
    threadlog.info("finished mirror indexing operation")


@devpiserver_hookimpl
def devpiserver_stage_created(stage):
    if stage.ixconfig["type"] == "mirror":
        threadlog.info("triggering load of initial projectnames for %s", stage.name)
        stage.list_projects_perstage()


@devpiserver_hookimpl
def devpiserver_cmdline_run(xom):
    if xom.config.args.recreate_search_index:
        if not xom.config.args.offline_mode:
            fatal("The --recreate-search-index option requires the --offline option.")
        ix = get_indexer(xom.config)
        ix.delete_index()
        indexer = get_indexer(xom.config)
        indexer.update_projects(iter_projects(xom), clear=True)
        # only exit when indexing explicitly
        return 0
    # allow devpi-server to run
    return None


def delete_project(stage, name):
    if stage is None:
        return
    ix = get_indexer(stage.xom.config)
    ix.delete_projects([preprocess_project(stage, name)])


def index_project(stage, name):
    if stage is None:
        return
    ix = get_indexer(stage.xom.config)
    ix.update_projects([preprocess_project(stage, name)])


@devpiserver_hookimpl
def devpiserver_on_upload(stage, project, version, link):
    if not link.entry.file_exists():
        # on replication or import we might be at a lower than
        # current revision and the file might have been deleted already
        threadlog.debug("ignoring lost upload: %s", link)
    elif link.rel == "doczip":
        index_project(stage, project)


@devpiserver_hookimpl
def devpiserver_on_changed_versiondata(stage, project, version, metadata):
    if stage is None:
        # TODO we don't have enough info to delete the project
        return
    if not metadata:
        if not stage.has_project_perstage(project):
            delete_project(stage, project)
            return
        versions = stage.list_versions(project)
        if versions:
            version = get_latest_version(versions)
            if version:
                threadlog.debug("A version of %s was deleted, using latest version %s for indexing" % (
                    project, version))
                metadata = stage.get_versiondata(project, version)
    if metadata:
        index_project(stage, metadata['name'])


@devpiserver_hookimpl(optionalhook=True)
def devpiserver_on_remove_file(stage, relpath):
    if relpath.endswith(".doc.zip"):
        project, version = (
            os.path.basename(relpath).rsplit('.doc.zip')[0].rsplit('-', 1)
        )
        remove_docs(stage, project, version)
