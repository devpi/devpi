
import py
from py.xml import html
from devpi_server.types import lazydecorator, cached_property
from bottle import response, request, abort, redirect, HTTPError, auth_basic
from bottle import BaseResponse, HTTPResponse, static_file
from devpi_server import urlutil
import bottle
import json
import itsdangerous
import logging

import requests

log = logging.getLogger(__name__)

LOGINCOOKIE = "devpi-login"
MAXDOCZIPSIZE = 30 * 1024 * 1024    # 30MB


def simple_html_body(title, bodytags, extrahead=""):
    return html.html(
        html.head(
            html.title(title),
            extrahead,
        ),
        html.body(
            html.h1(title),
            bodytags
        )
    )

#def abort_json(code, body):
#    d = dict(error=body)
#    raise HTTPResponse(body=json.dumps(d, indent=2)+"\n",
#                       status=code, headers=
#                       {"content-type": "application/json"})

def abort(code, body):
    if "application/json" in request.headers.get("Accept", ""):
        apireturn(code, body)
    bottle.abort(code, body)

def abort_authenticate():
    err = HTTPError(401, "authentication required")
    err.add_header('WWW-Authenticate', 'Basic realm="pypi"')
    err.add_header('location', "/+login")
    raise err

def apireturn(code, message=None, result=None, type=None):
    d = dict(status=code)
    if result is not None:
        assert type is not None
        d["result"] = result
        d["type"] = type
    if message:
        d["message"] = message
    data = json.dumps(d, indent=2) + "\n"
    raise HTTPResponse(body=data, status=code, header=
                    {"content-type": "application/json"})

def json_preferred():
    # XXX do proper "best" matching
    return "application/json" in request.headers.get("Accept", "")

route = lazydecorator()

class PyPIView:
    LOGIN_EXPIRATION = 60*60*10  # 10 hours

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
        if not self.db.user_exists(user):
            abort(404, "user %r does not exist" % user)
        if self.db.user_validate("root", ""):  # has empty password?
            return  # then we don't require any authentication
        try:
            authuser, authpassword = request.auth
        except TypeError:
            log.warn("could not read auth header")
            abort_authenticate()
        log.debug("detected auth for user %r", authuser)
        try:
            val = self.signer.unsign(authpassword, self.LOGIN_EXPIRATION)
        except itsdangerous.BadData:
            if self.db.user_validate(authuser, authpassword):
                return
            log.warn("invalid authentication for user %r", authuser)
            abort_authenticate()
        if not val.startswith(authuser + "-"):
            log.warn("mismatch credential for user %r", authuser)
            abort_authenticate()
        if authuser == "root" or authuser == user:
            return
        log.warn("user %r not authorized, requiring %r", authuser, user)
        abort_authenticate()

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
    # supplying basic API locations for all services
    #

    @route("/+api")
    @route("/<path:path>/+api")
    def apiconfig_index(self, path=None):
        api = {
            "resultlog": "/+tests",
            "login": "/+login",
        }
        if path:
            parts = path.split("/")
            if len(parts) >= 2:
                user, index = parts[:2]
                ixconfig = self.db.user_indexconfig_get(user, index)
                if not ixconfig:
                    abort(404, "index %s/%s does not exist" %(user, index))
                api.update({
                    "index": "/%s/%s/" % (user, index),
                    "simpleindex": "/%s/%s/+simple/" % (user, index),
                    "bases": ",".join(["%s/" % x for x in ixconfig["bases"]])
                })
                if ixconfig["type"] == "stage":
                    api["pypisubmit"] = "/%s/%s/" % (user, index)
        apireturn(200, type="apiconfig", result=api)

    #
    # index serving and upload

    #@route("/ext/pypi/simple<rest:re:.*>")  # deprecated
    #def extpypi_redirect(self, rest):
    #    redirect("/ext/pypi/+simple%s" % rest)

    @route("/<user>/<index>/+simple/<projectname>")
    @route("/<user>/<index>/+simple/<projectname>/")
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
            relpath = entry.relpath
            href = "/" + relpath
            if entry.eggfragment:
                href += "#egg=%s" % entry.eggfragment
            elif entry.md5:
                href += "#md5=%s" % entry.md5
            links.extend([
                 "/".join(relpath.split("/", 2)[:2]) + " ",
                 html.a(entry.basename, href=href),
                 html.br(),
            ])
        return simple_html_body("%s: links for %s" % (stage.name, projectname),
                                links).unicode()

    @route("/<user>/<index>/+simple/")
    def simple_list_all(self, user, index):
        stage = self.getstage(user, index)
        names = stage.getprojectnames()
        body = []
        for name in names:
            body.append(html.a(name, href=name + "/"))
            body.append(html.br())
        return simple_html_body("%s: list of accessed projects" % stage.name,
                                body).unicode()

    @route("/<user>/<index>", method=["PUT", "PATCH"])
    def index_create_or_modify(self, user, index):
        self.require_user(user)
        ixconfig = self.db.user_indexconfig_get(user, index)
        if request.method == "PUT" and ixconfig is not None:
            apireturn(409, "index %s/%s exists" % (user, index))
        kvdict = getkvdict_index(getjson())
        kvdict.setdefault("type", "stage")
        kvdict.setdefault("bases", ["root/dev"])
        kvdict.setdefault("volatile", True)
        ixconfig = self.db.user_indexconfig_set(user, index, **kvdict)
        apireturn(201, type="indexconfig", result=ixconfig)

    @route("/<user>/<index>", method=["GET"])
    def index_get(self, user, index):
        ixconfig = self.db.user_indexconfig_get(user, index)
        #if json_preferred():
        apireturn(200, type="indexconfig", result=ixconfig)

    @route("/<user>/<index>", method=["DELETE"])
    def index_delete(self, user, index):
        self.require_user(user)
        indexname = user + "/" + index
        if not self.db.user_indexconfig_delete(user, index):
            apireturn(404, "index %s does not exist" % indexname)
        self.db.delete_index(user, index)
        apireturn(201, "index %s deleted" % indexname)

    @route("/<user>/", method="GET")
    def index_list(self, user):
        userconfig = self.db.user_get(user)
        if not userconfig:
            apireturn(404, "user %s does not exist" % user)
        indexes = {}
        userindexes = userconfig.get("indexes", {})
        for name, val in userindexes.items():
            indexes["%s/%s" % (user, name)] = val
        apireturn(200, type="list:indexconfig", result=indexes)

    @route("/<user>/<index>/", method="PUSH")
    def pushrelease(self, user, index):
        pushdata = getjson()
        name = pushdata["name"]
        version = pushdata["version"]
        posturl = pushdata["posturl"]
        username = pushdata["username"]
        password = pushdata["password"]
        pypiauth = (username, password)
        stage = self.getstage(user, index)
        metadata = stage.get_metadata(name, version)
        assert metadata
        entries = stage.getreleaselinks(name)
        matches = []
        results = []
        for entry in entries:
            n, v = urlutil.guess_pkgname_and_version(entry.basename)
            if n == name and str(v) == version:
                matches.append(entry)
        metadata[":action"] = "submit"
        r = requests.post(posturl, data=metadata, auth=pypiauth)
        ok_codes = (200, 201)
        results.append((r.status_code, "register", name, version))
        if r.status_code in ok_codes:
            for entry in matches:
                metadata[":action"] = "file_upload"
                metadata["filetype"] = "sdist"  # XXX
                basename = entry.basename
                openfile = entry.FILE.filepath.open("rb")
                r = requests.post(posturl, data=metadata, auth=pypiauth,
                      files={"content": (basename, openfile)})
                results.append((r.status_code, "upload", entry.relpath))
        if r.status_code in ok_codes:
            apireturn(200, result=results, type="actionlog")
        else:
            apireturn(502, result=results, type="actionlog")

    @route("/<user>/<index>/", method="POST")
    def submit(self, user, index):
        if user == "root" and index == "pypi":
            abort(404, "cannot submit to pypi mirror")
        self.require_user(user)
        try:
            action = request.forms[":action"]
        except KeyError:
            abort(400, ":action field not found")
        stage = self.getstage(user, index)
        if action == "submit":
            return self._register_metadata(stage, request.forms)
        elif action in ("doc_upload", "file_upload"):
            try:
                content = request.files["content"]
            except KeyError:
                abort(400, "content file field not found")
            name = request.forms.get("name")
            version = request.forms.get("version", "")
            if not stage.get_metadata(name, version):
                self._register_metadata(stage, request.forms)
            if action == "file_upload":
                res = stage.store_releasefile(content.filename, content.value)
                if res == 409:
                    abort(409, "%s already exists in non-volatile index" %(
                         content.filename,))
            else:
                if len(content.value) > MAXDOCZIPSIZE:
                    abort(413, "zipfile too large")
                stage.store_doczip(name, content.value)
        else:
            abort(400, "action %r not supported" % action)
        return ""

    def _register_metadata(self, stage, form):
        metadata = {}
        for key in stage.metadata_keys:
            metadata[key] = form.get(key, "")
        log.info("got submit release info %r", metadata["name"])
        stage.register_metadata(metadata)

    #
    #  per-project and version data
    #

    # showing uploaded package documentation
    @route("/<user>/<index>/<name>/+doc/<relpath:re:.*>",
           method="GET")
    def doc_show(self, user, index, name, relpath):
        if not relpath:
            redirect("index.html")
        key = self.db.keyfs.STAGEDOCS(user=user, index=index, name=name)
        if not key.filepath.check():
            abort(404, "no documentation available")
        return static_file(relpath, root=str(key.filepath))

    @route("/<user>/<index>/<name>")
    @route("/<user>/<index>/<name>/")
    def project_get(self, user, index, name):
        stage = self.getstage(user, index)
        metadata = stage.get_projectconfig(name)
        #if not metadata:
        #    apireturn("404", "project %r does not exist" % name)
        if json_preferred():
            apireturn(200, type="projectconfig", result=metadata)
        # html
        body = []
        for version in urlutil.sorted_by_version(metadata.keys()):
            body.append(html.a(version, href=version + "/"))
            body.append(html.br())
        return simple_html_body("%s/%s: list of versions" % (stage.name,name),
                                body).unicode(indent=2)

    @route("/<user>/<index>/<name>", method="PUT")
    def project_add(self, user, index, name):
        self.require_user(user)
        stage = self.getstage(user, index)
        if stage.project_exists(name):
            apireturn(409, "project %r exists" % name)
        stage.project_add(name)
        apireturn(201, "project %r created" % name)

    @route("/<user>/<index>/<name>", method="DELETE")
    @route("/<user>/<index>/<name>/", method="DELETE")
    def project_delete(self, user, index, name):
        self.require_user(user)
        stage = self.getstage(user, index)
        if stage.name == "root/pypi":
            abort(405, "cannot delete on root/pypi index")
        if not stage.project_exists(name):
            apireturn(404, "project %r does not exist" % name)
        stage.project_delete(name)
        apireturn(200, "project %r deleted from stage %s" % (name, stage.name))

    @route("/<user>/<index>/<name>/<version>")
    @route("/<user>/<index>/<name>/<version>/")
    def version_get(self, user, index, name, version):
        stage = self.getstage(user, index)
        metadata = stage.get_projectconfig(name)
        if not metadata:
            abort(404, "project %r does not exist" % name)
        verdata = metadata.get(version, None)
        if not verdata:
            abort(404, "version %r does not exist" % version)
        if json_preferred():
            apireturn(200, type="versiondata", result=verdata)

        # if html show description and metadata
        rows = []
        for key, value in sorted(verdata.items()):
            if key == "description":
                continue
            rows.append(html.tr(html.td(key), html.td(value)))
        body = html.table(*rows)
        title = "%s/: %s-%s metadata and description" % (
                stage.name, name, version)

        content = stage.get_description(name, version)
        css = "https://pypi.python.org/styles/styles.css"
        return simple_html_body(title,
            [html.table(*rows), py.xml.raw(content)],
            extrahead=
            [html.link(media="screen", type="text/css",
                rel="stylesheet", title="text",
                href="https://pypi.python.org/styles/styles.css")]
        ).unicode(indent=2)

    @route("/<user>/<index>/<name>/<version>", method="DELETE")
    @route("/<user>/<index>/<name>/<version>/", method="DELETE")
    def project_version_delete(self, user, index, name, version):
        stage = self.getstage(user, index)
        if stage.name == "root/pypi":
            abort(405, "cannot delete on root/pypi index")
        metadata = stage.get_projectconfig(name)
        if not metadata:
            abort(404, "project %r does not exist" % name)
        verdata = metadata.get(version, None)
        if not verdata:
            abort(404, "version %r does not exist" % version)
        stage.project_version_delete(name, version)
        apireturn(200, "project %r version %r deleted" % (name, version))

    @route("/<user>/<index>/<name>/<version>/<relpath:re:.*>")
    @route("/<user>/<index>/f/<relpath:re:.*>")
    def pkgserv(self, user, index, name=None, version=None, relpath=None):
        relpath = request.path.strip("/")
        filestore = self.xom.releasefilestore
        headers, itercontent = filestore.iterfile(relpath, self.xom.httpget)
        response.content_type = headers["content-type"]
        if "content-length" in headers:
            response.content_length = headers["content-length"]
        for x in itercontent:
            yield x

    @route("/<user>/<index>/")
    def indexroot(self, user, index):
        stage = self.getstage(user, index)
        if json_preferred():
            projectlist = stage.getprojectnames_perstage()
            apireturn(200, type="list:projectconfig", result=projectlist)

        # XXX this should go to a template
        if hasattr(stage, "ixconfig"):
            bases = html.ul()
            for base in stage.ixconfig["bases"]:
                bases.append(html.li(
                    html.a("%s" % base, href="/%s/" % base),
                    " (",
                    html.a("simple", href="/%s/+simple/" % base),
                    " )",
                ))
            if bases:
                bases = [html.h2("inherited bases"), bases]
        else:
            bases = []
        latest_packages = html.ul()
        for name in stage.getprojectnames():
            for entry in stage.getreleaselinks(name):
                if entry.eggfragment:
                    continue
                if not entry.relpath.startswith(stage.name + "/"):
                    break
                if entry.url:
                    path = entry.url
                else:
                    path = entry.relpath
                name, ver = urlutil.DistURL(path).pkgname_and_version
                latest_packages.append(html.li(
                    html.a("%s-%s info page" % (name, ver),
                           href="%s/%s/" % (name, ver)),
                    " releasefiles: ",
                    html.a(entry.basename, href="/" + entry.relpath),
                ))
                break
        latest_packages = [
            html.h2("in-stage latest packages, at least as recent as bases"),
            latest_packages]

        return simple_html_body("%s index" % stage.name, [
            html.ul(
                html.li(html.a("simple index", href="+simple/")),
            ),
            latest_packages,
            bases,
        ]).unicode()



    #
    # login and user handling
    #
    @route("/+login", method="POST")
    def login(self):
        dict = getjson()
        user = dict.get("user", None)
        password = dict.get("password", None)
        if user is None or password is None:
            abort(400, "Bad request: no user/password specified")
        hash = self.db.user_validate(user, password)
        if hash:
            return self.set_user(user, hash)
        apireturn(401, "user %r could not be authenticated" % user)

    @route("/<user>", method="PATCH")
    @route("/<user>/", method="PATCH")
    def user_patch(self, user):
        self.require_user(user)
        dict = getjson()
        if "password" in dict:
            hash = self.db.user_setpassword(user, dict["password"])
            return self.set_user(user, hash)
        apireturn(400, "could not decode request")

    @route("/<user>", method="PUT")
    def user_create(self, user):
        if self.db.user_exists(user):
            apireturn(409, "user already exists")
        kvdict = getjson()
        if "password" in kvdict and "email" in kvdict:
            hash = self.db.user_create(user, **kvdict)
            apireturn(201, type="userconfig", result=self.db.user_get(user))
        apireturn(400, "password and email values need to be set")

    @route("/<user>", method="DELETE")
    def user_delete(self, user):
        self.require_user(user)
        if not self.db.user_exists(user):
            apireturn(404, "user %r does not exist" % user)
        self.db.user_delete(user)
        apireturn(200, "user %r deleted" % user)

    @route("/<user>", method="GET")
    def user_get(self, user):
        #self.require_user(user)
        userconfig = self.db.user_get(user)
        if not userconfig:
            apireturn(404, "user %r does not exist" % user)
        apireturn(200, type="userconfig", result=userconfig)

    @route("/", method="GET")
    def user_list(self):
        #accept = request.headers.get("accept")
        #if accept is not None:
        #    if accept.endswith("/json"):
        d = {}
        for user in self.db.user_list():
            d[user] = self.db.user_get(user)
        apireturn(200, type="list:userconfig", result=d)

def getjson():
    dict = request.json
    if dict is None:
        try:
            return json.load(request.body)
        except ValueError:
            abort(400, "Bad request: could not decode")
    return dict


def getkvdict_index(req):
    req_volatile = req.get("volatile")
    kvdict = dict(volatile=True, type="stage", bases=["root/dev"])
    if req_volatile is not None:
        if req_volatile == False or req_volatile.lower() in ["false", "no"]:
            kvdict["volatile"] = False
    bases = req.get("bases")
    if bases is not None:
        if not isinstance(bases, list):
            kvdict["bases"] = bases.split(",")
        else:
            kvdict["bases"] = bases
    if "type" in req:
        kvdict["type"] = req["type"]
    return kvdict
