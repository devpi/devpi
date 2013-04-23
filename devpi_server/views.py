from pyramid.view import view_config
from pyramid.response import Response

import logging
log = logging.getLogger(__name__)


@view_config(route_name='home', renderer='templates/mytemplate.pt')
def my_view(request):
    return {'project': 'devpi_server'}

@view_config(route_name="extpypi_simple",
             renderer='simple_project.mak')
def extpypi_simple(request):
    projectname = request.matchdict.get("projectname")
    entries = request.context.extdb.getreleaselinks(projectname)
    links = [("/pkg/%s#md5=%s" % (entry.relpath, entry.md5), entry.basename)
                for entry in entries]
    return {"projectlinks": links, "projectname": projectname}

@view_config(route_name="pkgserve")
def pkgserv(request):
    relpath = request.matchdict.get("relpath")
    assert relpath
    relpath = "/".join(relpath)
    headers, itercontent = request.context.releasefilestore.iterfile(
                relpath, request.context.httpget)
    r = Response(content_type=headers["content-type"],
                 app_iter=itercontent)
    r.content_length = headers["content-length"]
    log.info("returning response")
    return r
