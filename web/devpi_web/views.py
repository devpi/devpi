# coding: utf-8
from __future__ import unicode_literals
from devpi_common.types import ensure_unicode
from devpi_server.views import matchdict_parameters
from devpi_web.doczip import doc_key
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
