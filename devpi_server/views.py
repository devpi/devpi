from pyramid.view import view_config
from pyramid.response import Response

from logging import getLogger
log = getLogger(__name__)

from pyramid.view import notfound_view_config, view_config
@notfound_view_config(append_slash=True)
def notfound(request):
    return HTTPNotFound('Not found, bro.')

@view_config(route_name='home', renderer='templates/mytemplate.pt')
def my_view(request):
    return {'project': 'devpi_server'}

@view_config(route_name="extpypi_simple",
             renderer='simple_project.mak')
def extpypi_simple(request):
    projectname = request.matchdict.get("projectname")
    entries = request.context.extdb.getreleaselinks(projectname)
    links = []
    for entry in entries:
        href = "/pkg/" + entry.relpath
        if entry.eggfragment:
            href += "#egg=%s" % entry.eggfragment
        elif entry.md5:
            href += "#md5=%s" % entry.md5
        links.append((href, entry.basename))
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
