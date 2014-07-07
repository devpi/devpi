from __future__ import unicode_literals
from devpi_web.description import render_description
from devpi_web.doczip import unpack_docs
from devpi_web.indexing import iter_projects, preprocess_project
from devpi_web.whoosh_index import Index
from devpi_server.log import threadlog
from pyramid.renderers import get_renderer


def macros(request):
    renderer = get_renderer("templates/macros.pt")
    return renderer.implementation().macros


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
            url=request.route_url(
                "/{user}/{index}", user=user, index=index),
            title="%s/%s" % (user, index)))
    else:
        return result
    if 'name' in context.matchdict:
        name = context.name
        path.append(dict(
            url=request.route_url(
                "/{user}/{index}/{name}", user=user, index=index, name=name),
            title=name))
    else:
        return result
    if 'version' in context.matchdict:
        version = context.version
        if version == 'latest':
            stage = context.model.getstage(user, index)
            version = stage.get_latest_version(name)
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
    config.add_route(
        "toxresults",
        "/{user}/{index}/{name}/{version}/+toxresults/{basename}")
    config.add_route(
        "toxresult",
        "/{user}/{index}/{name}/{version}/+toxresults/{basename}/{toxresult}")
    config.add_request_method(macros, reify=True)
    config.add_request_method(navigation_info, reify=True)
    config.add_request_method(query_docs_html, reify=True)
    config.scan()


def get_indexer(config):
    indices_dir = config.serverdir.join('.indices')
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


def devpiserver_pypi_initial(stage, name2serials):
    xom = stage.xom
    ix = get_indexer(xom.config)
    ix.delete_index()
    indexer = get_indexer(xom.config)
    # directly use name2serials?
    indexer.update_projects(iter_projects(xom), clear=True)
    threadlog.info("finished initial indexing op")


def devpiserver_run_commands(xom):
    ix = get_indexer(xom.config)
    if xom.config.args.index_projects:
        ix.delete_index()
        indexer = get_indexer(xom.config)
        indexer.update_projects(iter_projects(xom), clear=True)
        # only exit when indexing explicitly
        return 0
    # allow devpi-server to run
    return None


def index_project(stage, name):
    if stage is None:
        return
    ix = get_indexer(stage.xom.config)
    ix.update_projects([preprocess_project(stage, name)])


def devpiserver_on_upload(stage, projectname, version, link):
    if not link.entry.file_exists():
        # on replication or import we might be at a lower than
        # current revision and the file might have been deleted already
        threadlog.debug("igoring lost upload: %s", link)
    elif link.rel == "doczip":
        unpack_docs(stage, projectname, version, link.entry)
        index_project(stage, projectname)


def devpiserver_on_changed_versiondata(stage, projectname, version, metadata):
    if metadata:
        render_description(stage, metadata)
        index_project(stage, metadata['name'])
    # else XXX handle deletion
