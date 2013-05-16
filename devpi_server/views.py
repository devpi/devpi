
from py.xml import html
from devpi_server.types import lazydecorator
from bottle import response, request, abort, redirect

def simple_html_body(title, bodytags):
    return html.html(
        html.head(
            html.title(title)
        ),
        html.body(
            html.h1(title),
            *bodytags
        )
    )

route = lazydecorator()

class PyPIView:
    def __init__(self, xom):
        self.xom = xom
        self.db = xom.db

    @route("/")
    @route("/ext/pypi/")
    def extpypi_redirect(self):
        redirect("/ext/pypi/simple/")

    #
    # supplying basic API locations for all services
    #

    @route("/<user>/<index>/-api")
    @route("/<user>/<index>/simple/-api")
    def apiconfig(self, user, index):
        root = "/"
        apidict = {
            "resultlog": "/resultlog",
            "pypisubmit": "/%s/%s/pypi" % (user, index),
            "pushrelease": "/%s/%s/push" % (user, index),
            "simpleindex": "/%s/%s/simple/" % (user, index),
        }
        return apidict

    #
    # serving the simple pages for an index
    #

    @route("/<user>/<index>/simple/<projectname>")
    @route("/<user>/<index>/simple/<projectname>/")
    def simple_list_project(self, user, index, projectname):
        # we only serve absolute links so we don't care about the route's slash
        stagename = self.db.getstagename(user, index)
        result = self.db.getreleaselinks(stagename, projectname)
        if isinstance(result, int):
            if result == 404:
                abort(404, "no such project")
            if result >= 500:
                abort(502, "upstream server has internal error")
            if result < 0:
                abort(502, "upstream server not reachable")

        links = []
        for entry in result:
            href = "/pkg/" + entry.relpath
            if entry.eggfragment:
                href += "#egg=%s" % entry.eggfragment
            elif entry.md5:
                href += "#md5=%s" % entry.md5
            links.append((href, entry.basename))

        # construct html
        body = []
        for entry in links:
            body.append(html.a(entry[1], href=entry[0]))
            body.append(html.br())
        return simple_html_body("links for %s" % projectname, body).unicode()

    @route("/<user>/<index>/simple/")
    def simple_list_all(self, user, index):
        stagename = self.db.getstagename(user, index)
        names = self.db.getprojectnames(stagename)
        body = []
        for name in names:
            body.append(html.a(name, href=name + "/"))
            body.append(html.br())
        return simple_html_body("list of accessed projects", body).unicode()


class PkgView:
    def __init__(self, filestore, httpget):
        self.filestore = filestore
        self.httpget = httpget

    @route("/pkg/<relpath:re:.*>")
    def pkgserv(self, relpath):
        headers, itercontent = self.filestore.iterfile(relpath, self.httpget)
        response.content_type = headers["content-type"]
        if "content-length" in headers:
            response.content_length = headers["content-length"]
        for x in itercontent:
            yield x
