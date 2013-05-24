
from py.xml import html
from devpi_server.types import lazydecorator
from bottle import response, request, abort, redirect
import logging

log = logging.getLogger(__name__)

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

    def getstage(self, user, index):
        stage = self.db.getstage(user, index)
        if not stage:
            abort(404, "no such stage")
        return stage

    @route("/")
    @route("/ext/pypi/")
    def extpypi_redirect(self):
        redirect("/ext/pypi/simple/")

    #
    # supplying basic API locations for all services
    #

    @route("/<user>/<index>/-api")
    @route("/<user>/<index>/pypi/-api")
    @route("/<user>/<index>/simple/-api")
    def apiconfig(self, user, index):
        root = "/"
        apidict = {
            "resultlog": "/resultlog",
            "indexadmin": "/indexadmin",
            "pypisubmit": "/%s/%s/pypi" % (user, index),
            "pushrelease": "/%s/%s/push" % (user, index),
            "simpleindex": "/%s/%s/simple/" % (user, index),
        }
        return apidict

    #
    # serving the simple pages for an index
    #

    @route("/<user>/<index>/")
    def indexroot(self, user, index):
        stage = self.getstage(user, index)
        bases = html.ul()
        for base in stage.ixconfig["bases"]:
            bases.append(html.li(
                html.a("%s" % base, href="/%s/" % base),
                " (",
                html.a("simple", href="/%s/simple/" % base),
                " )",
            ))
        if bases:
            bases = [html.h2("inherited bases"), bases]

        return simple_html_body("%s index" % stage.name, [
            html.ul(
                html.li(html.a("simple index", href="simple/")),
            ),
            bases,
        ]).unicode()

    @route("/<user>/<index>/simple/<projectname>")
    @route("/<user>/<index>/simple/<projectname>/")
    def simple_list_project(self, user, index, projectname):
        # we only serve absolute links so we don't care about the route's slash
        stage = self.getstage(user, index)
        result = stage.getreleaselinks(projectname)
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
        return simple_html_body("%s: links for %s" % (stage.name, projectname),
                                body).unicode()

    @route("/<user>/<index>/simple/")
    def simple_list_all(self, user, index):
        stage = self.getstage(user, index)
        names = stage.getprojectnames()
        body = []
        for name in names:
            body.append(html.a(name, href=name + "/"))
            body.append(html.br())
        return simple_html_body("%s: list of accessed projects" % stage.name,
                                body).unicode()

    @route("/<user>/<index>/pypi", method="POST")
    @route("/<user>/<index>/pypi/", method="POST")
    def upload(self, user, index):
        try:
            action = request.forms[":action"]
        except KeyError:
            abort(400, output=":action field not found")
        stage = self.getstage(user, index)
        if action == "submit":
            return ""
        elif action == "file_upload":
            try:
                content = request.files["content"]
            except KeyError:
                abort(400, "content file field not found")
            #name = request.forms.get("name")
            #version = request.forms.get("version")
            stage.store_releasefile(content.filename, content.value)
        else:
            abort(400, output="action %r not supported" % action)
        return ""


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
