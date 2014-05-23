# coding: utf-8
from __future__ import unicode_literals
from devpi_common.metadata import splitbasename
from devpi_common.types import ensure_unicode
from devpi_server.views import matchdict_parameters
from devpi_web.doczip import doc_key
from operator import itemgetter
from py.xml import html
from pyramid.compat import decode_path_info
from pyramid.httpexceptions import HTTPFound, HTTPNotFound
from pyramid.httpexceptions import default_exceptionresponse_view
from pyramid.interfaces import IRoutesMapper
from pyramid.response import FileResponse
from pyramid.view import notfound_view_config, view_config
import logging
import py


log = logging.getLogger(__name__)


# showing uploaded package documentation
@view_config(route_name="docroot", request_method="GET")
@matchdict_parameters
def doc_show(request, user, index, name, version, relpath):
    if not relpath:
        raise HTTPFound(location="index.html")
    xom = request.registry['xom']
    stage = xom.model.getstage(user, index)
    if not stage:
        raise HTTPNotFound("no such stage")
    key = doc_key(stage, name, version)
    if not key.filepath.check():
        raise HTTPNotFound("no documentation available")
    return FileResponse(str(key.filepath.join(relpath)))


@notfound_view_config(request_method="GET")
def notfound(request):
    path = decode_path_info(request.environ['PATH_INFO'] or '/')
    registry = request.registry
    mapper = registry.queryUtility(IRoutesMapper)
    if mapper is not None and path.endswith('/'):
        # redirect URLs with a trailing slash to URLs without one, if there
        # is a matching route
        nonslashpath = path.rstrip('/')
        for route in mapper.get_routes():
            if route.match(nonslashpath) is not None:
                qs = request.query_string
                if qs:
                    qs = '?' + qs
                return HTTPFound(location=nonslashpath + qs)
    return default_exceptionresponse_view(None, request)


def get_files_info(request, user, index, metadata):
    xom = request.registry['xom']
    files = []
    filedata = metadata.get("+files", {})
    if not filedata:
        log.warn(
            "project %r version %r has no files",
            metadata["name"], metadata.get("version"))
    for basename in sorted(filedata):
        entry = xom.filestore.getentry(filedata[basename])
        files.append(dict(
            title=basename,
            url=request.route_url(
                "/{user}/{index}/+f/{relpath:.*}",
                user=user, index=index,
                relpath="%s/%s" % (entry.md5, entry.basename))))
    return files


def get_docs_info(request, stage, metadata):
    if stage.name == 'root/pypi':
        return
    name, ver = metadata["name"], metadata["version"]
    dockey = doc_key(stage, name, ver)
    if dockey.exists():
        return dict(
            title="%s-%s docs" % (name, ver),
            url=request.route_url(
                "docroot", user=stage.user.name, index=stage.index,
                name=name, version=ver, relpath="index.html"))


@view_config(
    route_name='root',
    renderer='templates/root.pt')
def root(request):
    xom = request.registry['xom']
    rawusers = sorted(
        (x.get() for x in xom.model.get_userlist()),
        key=itemgetter('username'))
    users = []
    for user in rawusers:
        username = user['username']
        indexes = []
        for index in sorted(user.get('indexes', [])):
            indexes.append(dict(
                title="%s/%s" % (username, index),
                url=request.route_url(
                    "/{user}/{index}", user=username, index=index)))
        users.append(dict(
            title=username,
            indexes=indexes))
    return dict(users=users)


@view_config(
    route_name="/{user}/{index}", accept="text/html", request_method="GET",
    renderer="templates/index.pt")
@matchdict_parameters
def index_get(request, user, index):
    xom = request.registry['xom']
    stage = xom.model.getstage(user, index)
    if not stage:
        raise HTTPNotFound("no such stage")
    bases = []
    packages = []
    result = dict(
        title="%s index" % stage.name,
        simple_index_url=request.route_url(
            "/{user}/{index}/+simple/", user=user, index=index),
        bases=bases,
        packages=packages)
    if stage.name == "root/pypi":
        return result

    if hasattr(stage, "ixconfig"):
        for base in stage.ixconfig["bases"]:
            base_user, base_index = base.split('/')
            bases.append(dict(
                title=base,
                url=request.route_url(
                    "/{user}/{index}",
                    user=base_user, index=base_index),
                simple_url=request.route_url(
                    "/{user}/{index}/+simple/",
                    user=base_user, index=base_index)))

    for projectname in stage.getprojectnames_perstage():
        metadata = stage.get_metadata_latest_perstage(projectname)
        try:
            name, ver = metadata["name"], metadata["version"]
        except KeyError:
            log.error("metadata for project %r empty: %s, skipping",
                      projectname, metadata)
            continue
        packages.append(dict(
            info=dict(
                title="%s-%s info page" % (name, ver),
                url=request.route_url(
                    "/{user}/{index}/{name}/{version}",
                    user=stage.user.name, index=stage.index,
                    name=name, version=ver)),
            files=get_files_info(request, stage.user.name, stage.index, metadata),
            docs=get_docs_info(request, stage, metadata)))

    return result


@view_config(
    route_name="/{user}/{index}/{name}",
    accept="text/html", request_method="GET",
    renderer="templates/project.pt")
@matchdict_parameters
def project_get(request, user, index, name):
    xom = request.registry['xom']
    stage = xom.model.getstage(user, index)
    if not stage:
        raise HTTPNotFound("no such stage")
    name = ensure_unicode(name)
    releases = stage.getreleaselinks(name)
    if not releases:
        raise HTTPNotFound("project %r does not exist" % name)
    versions = []
    for release in releases:
        name, version = splitbasename(release)[:2]
        versions.append(dict(
            title=version,
            url=request.route_url(
                "/{user}/{index}/{name}/{version}",
                user=user, index=index, name=name, version=version)))
    return dict(
        title="%s/: %s versions" % (stage.name, name),
        versions=versions)


@view_config(
    route_name="/{user}/{index}/{name}/{version}",
    accept="text/html", request_method="GET",
    renderer="templates/version.pt")
@matchdict_parameters
def version_get(request, user, index, name, version):
    xom = request.registry['xom']
    stage = xom.model.getstage(user, index)
    if not stage:
        raise HTTPNotFound("no such stage")
    name = ensure_unicode(name)
    version = ensure_unicode(version)
    metadata = stage.get_projectconfig(name)
    if not metadata:
        raise HTTPNotFound("project %r does not exist" % name)
    verdata = metadata.get(version, None)
    if not verdata:
        raise HTTPNotFound("version %r does not exist" % version)
    infos = []
    for key, value in sorted(verdata.items()):
        if key == "description" or key.startswith('+'):
            continue
        if isinstance(value, list):
            value = html.ul([html.li(x) for x in value]).unicode()
        else:
            value = py.xml.escape(value)
        infos.append((py.xml.escape(key), value))
    return dict(
        title="%s/: %s-%s metadata and description" % (stage.name, name, version),
        content=stage.get_description(name, version),
        infos=infos,
        files=get_files_info(request, user, index, verdata),
        docs=get_docs_info(request, stage, verdata))


def batch_list(num, current, left=3, right=3):
    result = []
    if not num:
        return result
    if current >= num:
        raise ValueError("Current position (%s) can't be greater than total (%s)." % (current, num))
    result.append(0)
    first = current - left
    if first < 1:
        first = 1
    if first > 1:
        result.append(None)
    last = current + right + 1
    if last >= num:
        last = num - 1
    result.extend(range(first, last))
    if last < (num - 1):
        result.append(None)
    if num > 1:
        result.append(num - 1)
    return result


@view_config(
    route_name='search',
    renderer='templates/search.pt')
def search(request):
    params = dict(request.params)
    params['query'] = params.get('query', '')
    try:
        params['page'] = int(params.get('page'))
    except TypeError:
        params['page'] = 1
    batch_links = []
    if params['query']:
        search_index = request.registry['search_index']
        result = search_index.query_projects(
            params['query'], page=params['page'])
        result_info = result['info']
        for item in batch_list(result_info['pagecount'], result_info['pagenum'] - 1):
            if item is None:
                batch_links.append(dict(
                    title='…'))
            elif item == (params['page'] - 1):
                batch_links.append(dict(
                    title=item + 1))
            else:
                new_params = dict(params)
                new_params['page'] = item + 1
                batch_links.append(dict(
                    title=item + 1,
                    url=request.route_url(
                        'search',
                        _query=new_params)))
        for item in result['items']:
            data = item['data']
            if 'version' in data:
                item['url'] = request.route_url(
                    "/{user}/{index}/{name}/{version}",
                    user=data['user'], index=data['index'],
                    name=data['name'], version=data['version'])
            else:
                item['url'] = request.route_url(
                    "/{user}/{index}/{name}",
                    user=data['user'], index=data['index'], name=data['name'])
            for sub_hit in item['sub_hits']:
                sub_hit['title'] = sub_hit['data'].get(
                    'text_title', sub_hit['data']['text_type'])
                text_path = sub_hit['data'].get('text_path')
                if text_path:
                    sub_hit['url'] = request.route_url(
                        "docroot", user=data['user'], index=data['index'],
                        name=data['name'], version=data['doc_version'],
                        relpath="%s.html" % text_path)
            more_results = result_info['collapsed_counts'][data['path']]
            if more_results:
                new_params = dict(params)
                new_params['query'] = "%s path:%s" % (params['query'], data['path'])
                item['more_url'] = request.route_url(
                    'search',
                    _query=new_params)
                item['more_count'] = more_results
    else:
        result = None
    return dict(
        query=params['query'],
        page=params['page'],
        batch_links=batch_links,
        result=result)
