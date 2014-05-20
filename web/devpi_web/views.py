# coding: utf-8
from __future__ import unicode_literals
from devpi_server.views import matchdict_parameters
from devpi_web.doczip import doc_key
from pyramid.httpexceptions import HTTPFound, HTTPNotFound
from pyramid.response import FileResponse
from pyramid.view import view_config


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
