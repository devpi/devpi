
from py.xml import html
from devpi_server.types import lazydecorator, cached_property
from bottle import response, request, abort, redirect, HTTPError, auth_basic
import json
import itsdangerous
import logging

log = logging.getLogger(__name__)

LOGINCOOKIE = "devpi-login"

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

class Auth:
    def __init__(self, user):
        self.user = user
        self.roles = ["user"]

class PyPIView:
    LOGIN_EXPIRATION = 60*60*10

    def __init__(self, xom):
        self.xom = xom
        self.db = xom.db

    #
    # support functions
    #

    @cached_property
    def signer(self):
        return itsdangerous.TimestampSigner(self.xom.config.secret)

    def require_user(self, user):
        #log.debug("headers %r", request.headers.items())
        try:
            authuser, authpassword = request.auth
        except TypeError:
            log.warn("could not read auth header")
            err = HTTPError(401, "authentication required")
            err.add_header('WWW-Authenticate', 'Basic realm="devpi"')
            raise err
        log.debug("detected auth for user %r", authuser)
        try:
            val = self.signer.unsign(authpassword, self.LOGIN_EXPIRATION)
        except itsdangerous.BadData:
            abort(401, "invalid authentication for user %r" % authuser)
        if not val.startswith(authuser + "-"):
            abort(401, "mismatch credential for user %r" % authuser)
        if authuser == "admin" or authuser == user:
            return
        abort(401, "user %r not authorized, requiring %r" % (authuser, user))

    def set_user(self, user, hash):
        pseudopass = self.signer.sign(user + "-" + hash)
        return {"password":  pseudopass,
                "expiration": self.LOGIN_EXPIRATION}

    def getstage(self, user, index):
        stage = self.db.getstage(user, index)
        if not stage:
            abort(404, "no such stage")
        return stage

    #
    # index serving and upload
    #

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
    @route("/<user>/<index>/", method="GET")
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

    @route("/<user>/<index>", method="PUT")
    def index_create(self, user, index):
        ixconfig = self.db.user_indexconfig_get(user, index)
        if ixconfig is not None:
            abort(409, "index exists")
        ixconfig = self.db.user_indexconfig_set(user, index,
            type="private",
            volatile=True,
            bases=["int/dev"],
        )
        response.status = 201
        return ixconfig

    @route("/<user>/<index>/pypi", method="POST")
    @route("/<user>/<index>/pypi/", method="POST")
    def upload(self, user, index):
        self.require_user(user)
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
            "login": "/login",
            "pypisubmit": "/%s/%s/pypi" % (user, index),
            "pushrelease": "/%s/%s/push" % (user, index),
            "simpleindex": "/%s/%s/simple/" % (user, index),
        }
        return apidict

    #
    # login and user handling
    #
    @route("/login", method="POST")
    def login(self):
        dict = getjson()
        user = dict.get("user", None)
        password = dict.get("password", None)
        if user is None or password is None:
            abort(400, "Bad request: no user/password specified")
        hash = self.db.user_validate(user, password)
        if hash:
            return self.set_user(user, hash)
        abort(401, "user could not be authenticated")

    @route("/<user>", method="PATCH")
    @route("/<user>/", method="PATCH")
    def user_patch(self, user):
        self.require_user(user)
        dict = getjson()
        if "password" in dict:
            hash = self.db.user_setpassword(user, dict["password"])
            return self.set_user(user, hash)
        abort(400, "could not decode")

    @route("/<user>", method="PUT")
    def user_create(self, user):
        dict = getjson()
        if "password" in dict:
            if self.db.user_exists(user):
                abort(409, "user already exists")
            hash = self.db.user_setpassword(user, dict["password"])
            response.status = 201
            return "user %r created" % user
        abort(400, "could not decode")

    @route("/<user>", method="DELETE")
    def user_delete(self, user):
        self.require_user(user)
        if not self.db.user_exists(user):
            abort(404, "used %r does not exist" % user)
        self.db.user_delete(user)
        return "user %r deleted" % user

    @route("/", method="GET")
    def user_list(self):
        accept = request.headers.get("accept")
        if accept is not None:
            if accept.endswith("/json"):
                l = list(self.db.user_list())
                return {"users": l}
        abort(404, "no resource found")


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

def getjson():
    dict = request.json
    if dict is None:
        try:
            return json.load(request.body)
        except ValueError:
            abort(400, "Bad request: could not decode")
    return dict

