from __future__ import unicode_literals
from devpi_web.doczip import unpack_docs
from devpi_web.indexing import iter_projects, preprocess_project
from devpi_web.whoosh_index import Index
from pyramid.renderers import get_renderer


def macros(request):
    renderer = get_renderer("templates/macros.pt")
    return renderer.implementation().macros


def navigation_info(request):
    path = [dict(
        url=request.route_url("root"),
        title="devpi")]
    result = dict(path=path)
    if 'user' in request.matchdict:
        user = request.matchdict['user']
    else:
        return result
    if 'index' in request.matchdict:
        index = request.matchdict['index']
        path.append(dict(
            url=request.route_url(
                "/{user}/{index}", user=user, index=index),
            title="%s/%s" % (user, index)))
    else:
        return result
    if 'name' in request.matchdict:
        name = request.matchdict['name']
        path.append(dict(
            url=request.route_url(
                "/{user}/{index}/{name}", user=user, index=index, name=name),
            title=name))
    else:
        return result
    if 'version' in request.matchdict:
        version = request.matchdict['version']
        path.append(dict(
            url=request.route_url(
                "/{user}/{index}/{name}/{version}",
                user=user, index=index, name=name, version=version),
            title=version))
    else:
        return result
    return result


def query_docs_html(request):
    search_index = request.registry['search_index']
    return search_index.get_query_parser_html_help()


def includeme(config):
    config.include('pyramid_chameleon')
    config.add_static_view('static', 'static')
    config.add_route('root', '/', accept='text/html')
    config.add_route('search', '/+search', accept='text/html')
    config.add_route('search_help', '/+searchhelp', accept='text/html')
    config.add_route(
        "docroot",
        "/{user}/{index}/{name}/{version}/+doc/{relpath:.*}")
    config.add_route(
        "docviewroot",
        "/{user}/{index}/{name}/{version}/+d/{relpath:.*}")
    config.add_request_method(macros, reify=True)
    config.add_request_method(navigation_info, reify=True)
    config.add_request_method(query_docs_html, reify=True)
    config.scan()


def get_indexer(config):
    indices_dir = config.serverdir.join('.indices', abs=True)
    indices_dir.ensure_dir()
    return Index(indices_dir.strpath)


def devpiserver_pyramid_configure(config, pyramid_config):
    # by using include, the package name doesn't need to be set explicitly
    # for registrations of static views etc
    pyramid_config.include('devpi_web.main')
    pyramid_config.registry['search_index'] = get_indexer(config)


def devpiserver_add_parser_options(parser):
    indexing = parser.addgroup("indexing")
    indexing.addoption(
        "--index-projects", action="store_true",
        help="index all existing projects")


def devpiserver_run_commands(xom):
    ix = get_indexer(xom.config)
    if ix.needs_reindex() or xom.config.args.index_projects:
        ix.delete_index()
        indexer = get_indexer(xom.config)
        indexer.update_projects(iter_projects(xom), clear=True)
        if xom.config.args.index_projects:
            # only exit when indexing explicitly
            return 0
    # allow devpi-server to run
    return None


def index_project(stage, name):
    ix = get_indexer(stage.xom.config)
    pconfig = stage.get_projectconfig(name)
    ix.update_projects([preprocess_project(stage, name, pconfig)])


def devpiserver_docs_uploaded(stage, name, version, entry):
    unpack_docs(stage, name, version, entry)
    index_project(stage, name)


def devpiserver_register_metadata(stage, metadata):
    index_project(stage, metadata['name'])
