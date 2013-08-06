
import py
from py.xml import html
from devpi_server.types import lazydecorator, cached_property
from bottle import response, request, abort, redirect, HTTPError, auth_basic
from bottle import BaseResponse, HTTPResponse, static_file
from devpi_server.config import render_string
from devpi_server import urlutil
import bottle
import json
import itsdangerous
import logging
import inspect

import requests

log = logging.getLogger(__name__)

LOGINCOOKIE = "devpi-login"
MAXDOCZIPSIZE = 30 * 1024 * 1024    # 30MB

static_dir = py.path.local(__file__).dirpath("+static").strpath

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

    def get_auth_user(self):
        try:
            authuser, authpassword = request.auth
        except TypeError:
            log.debug("could not read auth header")
            return None
        try:
            val = self.signer.unsign(authpassword, self.LOGIN_EXPIRATION)
        except itsdangerous.BadData:
            if self.db.user_validate(authuser, authpassword):
                return authuser
            return None
        else:
            if not val.startswith(authuser + "-"):
                log.debug("mismatch credential for user %r", authuser)
                return None
            return authuser

    def require_user(self, user, stage=None, acltype="upload"):
        #log.debug("headers %r", request.headers.items())
        if not self.db.user_exists(user):
            abort(404, "user %r does not exist" % user)
        if self.db.user_validate("root", ""):  # has empty password?
            return  # then we don't require any authentication
        auth_user = self.get_auth_user()
        if not auth_user:
            log.warn("invalid or no authentication")
            abort_authenticate()
        if auth_user == "root" or auth_user == user:
            return
        if stage:
            acl = stage.ixconfig.get("acl_" + acltype, [])
            if auth_user in acl:
                log.debug("user %r is acl_upload list", auth_user)
                return
        log.info("user %r not authorized", auth_user)
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
    # attachment to release files
    # currently only test results, pending generalization
    #

    @route("/+tests", method="POST")
    def add_attach(self):
        filestore = self.xom.releasefilestore
        data = getjson()
        md5 = data["installpkg"]["md5"]
        num = filestore.add_attachment(md5=md5, type="toxresult",
                                       data=request.body.read())
        relpath = "/+tests/%s/%s/%s" %(md5, "toxresult", num)
        apireturn(200, type="testresultpath", result=relpath)

    @route("/+tests/<md5>/<type>", method="GET")
    def get_attachlist(self, md5, type):
        filestore = self.xom.releasefilestore
        datalist = list(filestore.iter_attachments(md5=md5, type=type))
        apireturn(200, type="list:toxresult", result=datalist)

    @route("/+tests/<md5>/<type>/<num>", method="GET")
    def get_attach(self, md5, type, num):
        filestore = self.xom.releasefilestore
        data = filestore.get_attachment(md5=md5, type=type, num=num)
        apireturn(200, type="testresult", result=data)

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
        try:
            ixconfig = self.db.user_indexconfig_set(user, index, **kvdict)
        except self.db.InvalidIndexconfig as e:
            apireturn(400, message=", ".join(e.messages))
        apireturn(200, type="indexconfig", result=ixconfig)

    @route("/<user>/<index>", method=["GET"])
    def index_get(self, user, index):
        stage = self.getstage(user, index)
        apireturn(200, type="indexconfig", result=stage.ixconfig)

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
        stage = self.getstage(user, index)
        pushdata = getjson()
        try:
            name = pushdata["name"]
            version = pushdata["version"]
        except KeyError:
            apireturn(400, message="no name/version specified in json")

        metadata = stage.get_metadata(name, version)
        entries = stage.getreleaselinks_perstage(name)
        matches = []
        for entry in entries:
            n, v = urlutil.guess_pkgname_and_version(entry.basename)
            if n == name and str(v) == version:
                matches.append(entry)
        if not matches or not metadata:
            log.info("%s: no release files %s-%s" %(stage.name, name, version))
            apireturn(404,
                      message="no release/files found for %s-%s" %(
                      name, version))

        # prepare metadata for submission
        metadata[":action"] = "submit"

        results = []
        targetindex = pushdata.get("targetindex", None)
        if targetindex is not None:
            parts = targetindex.split("/")
            if len(parts) != 2:
                apireturn(400, message="targetindex not in format user/index")
            target_stage = self.getstage(*parts)
            auth_user = self.get_auth_user()
            log.debug("targetindex %r, auth_user %r", targetindex, auth_user)
            if not target_stage.can_upload(auth_user):
               apireturn(401, message="user %r cannot upload to %r"
                                      %(auth_user, targetindex))
            #results = stage.copy_release(metadata, target_stage)
            #results.append((r.status_code, "upload", entry.relpath))
            #apireturn(200, results=results, type="actionlog")
            if not target_stage.get_metadata(name, version):
                self._register_metadata(target_stage, metadata)
            results.append((200, "register", name, version,
                            "->", target_stage.name))
            for entry in matches:
                res = target_stage.store_releasefile(
                    entry.basename, entry.FILE.filepath.read(mode="rb"))
                if not isinstance(res, int):
                    res = 200
                results.append((res, "store_releasefile", entry.basename,
                                "->", target_stage.name))
            apireturn(200, result=results, type="actionlog")
        else:
            posturl = pushdata["posturl"]
            username = pushdata["username"]
            password = pushdata["password"]
            pypiauth = (username, password)
            log.info("registering %s-%s to %s", name, version, posturl)
            r = requests.post(posturl, data=metadata, auth=pypiauth)
            log.debug("register returned: %s", r.status_code)
            ok_codes = (200, 201)
            results.append((r.status_code, "register", name, version))
            if r.status_code in ok_codes:
                for entry in matches:
                    metadata[":action"] = "file_upload"
                    basename = entry.basename
                    pyver, filetype = urlutil.get_pyversion_filetype(basename)
                    metadata["filetype"] = filetype
                    metadata["pyversion"] = pyver
                    openfile = entry.FILE.filepath.open("rb")
                    log.info("sending %s to %s", basename, posturl)
                    r = requests.post(posturl, data=metadata, auth=pypiauth,
                          files={"content": (basename, openfile)})
                    log.debug("send finished, status: %s", r.status_code)
                    results.append((r.status_code, "upload", entry.relpath))
            if r.status_code in ok_codes:
                apireturn(200, result=results, type="actionlog")
            else:
                apireturn(502, result=results, type="actionlog")

    @route("/<user>/<index>/", method="POST")
    def submit(self, user, index):
        if user == "root" and index == "pypi":
            abort(404, "cannot submit to pypi mirror")
        stage = self.getstage(user, index)
        self.require_user(user, stage=stage)
        try:
            action = request.forms[":action"]
        except KeyError:
            abort(400, ":action field not found")
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
                trigger_jenkins(stage, name)
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
        stage.register_metadata(metadata)
        log.info("%s: got submit release info %r",
                 stage.name, metadata["name"])

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
        if json_preferred():
            entry = filestore.getentry(relpath)
            if not entry.exists():
                apireturn(404, "no such release file")
            apireturn(200, type="releasefilemeta", result=entry._mapping)
        headers, itercontent = filestore.iterfile(relpath, self.xom.httpget)
        if headers is None:
            abort(404, "no such file")
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
                dockey = self.db.keyfs.STAGEDOCS(user=user,
                                                 index=index, name=name)
                if dockey.exists():
                    docs = [" docs: ", html.a("%s-%s docs" %(name, ver),
                                href="%s/+doc/index.html" %(name))]
                else:
                    docs = []

                latest_packages.append(html.li(
                    html.a("%s-%s info page" % (name, ver),
                           href="%s/%s/" % (name, ver)),
                    " releasefiles: ",
                    html.a(entry.basename, href="/" + entry.relpath),
                    *docs
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
        #log.debug("got password %r" % password)
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
        if "password" in kvdict:  # and "email" in kvdict:
            hash = self.db.user_create(user, **kvdict)
            apireturn(201, type="userconfig", result=self.db.user_get(user))
        apireturn(400, "password needs to be set")

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
            abort(400, "Bad request: could not decode json")
    return dict

def get_outside_url(headers, outsideurl):
    if outsideurl:
        url = outsideurl
    else:
        url = headers.get("X-outside-url", None)
        if url is None:
            url = "http://" + headers.get("Host")
    url = url.rstrip("/") + "/"
    log.debug("host header: %s", url)
    return url

def trigger_jenkins(stage, testspec):
    jenkins_url = stage.ixconfig["uploadtrigger_jenkins"]
    if not jenkins_url:
        return
    jenkins_url = jenkins_url.format(pkgname=testspec)
    baseurl = get_outside_url(request.headers,
                              stage.xom.config.args.outside_url)

    source = render_string("devpibootstrap.py",
        INDEXURL=baseurl + stage.name,
        VIRTUALENVTARURL= (baseurl +
            "root/pypi/f/https/pypi.python.org/packages/"
            "source/v/virtualenv/virtualenv-1.10.tar.gz"),
        TESTSPEC=testspec,
        DEVPI_INSTALL_INDEX = baseurl + stage.name + "/+simple/"
    )
    inputfile = py.io.BytesIO(source)
    r = requests.post(jenkins_url, data={
                    "Submit": "Build",
                    "name": "jobscript.py",
                    "json": json.dumps(
                {"parameter": {"name": "jobscript.py", "file": "file0"}}),
        },
            files={"file0": ("file0", inputfile)})

    if r.status_code == 200:
        log.info("successfully triggered jenkins: %s", jenkins_url)
    else:
        log.error("%s: failed to trigger jenkins at %s", r.status_code,
                  jenkins_url)


def getkvdict_index(req):
    req_volatile = req.get("volatile")
    kvdict = dict(volatile=True, type="stage", bases=["root/dev"])
    if req_volatile is not None:
        if req_volatile == False or (req_volatile != True and
            req_volatile.lower() in ["false", "no"]):
            kvdict["volatile"] = False
    bases = req.get("bases")
    if bases is not None:
        if not isinstance(bases, list):
            kvdict["bases"] = bases.split(",")
        else:
            kvdict["bases"] = bases
    if "type" in req:
        kvdict["type"] = req["type"]
    if "acl_upload" in req:
        kvdict["acl_upload"] = req["acl_upload"]
    if "uploadtrigger_jenkins" in req:
        kvdict["uploadtrigger_jenkins"] = req["uploadtrigger_jenkins"]
    return kvdict
