from __future__ import unicode_literals
import py
from py.xml import html
from devpi_common.types import lazydecorator, ensure_unicode
from devpi_common.url import URL
from devpi_common.metadata import get_pyversion_filetype
import devpi_server
from bottle import response, request, redirect, HTTPError
from bottle import HTTPResponse, static_file
import json
import logging
from devpi_common.request import new_requests_session
from devpi_common.validation import normalize_name, is_valid_archive_name

from .auth import Auth
from .config import render_string

server_version = devpi_server.__version__

log = logging.getLogger(__name__)

MAXDOCZIPSIZE = 30 * 1024 * 1024    # 30MB

static_dir = py.path.local(__file__).dirpath("+static").strpath

def simple_html_body(title, bodytags, extrahead=""):
    return html.html(
        html.head(
            html.title(title),
            extrahead,
        ),
        html.body(
            html.h1(title), "\n",
            bodytags
        )
    )

#def abort_json(code, body):
#    d = dict(error=body)
#    raise HTTPResponse(body=json.dumps(d, indent=2)+"\n",
#                       status=code, headers=
#                       {"content-type": "application/json"})

API_VERSION = "1"

# we use str() here so that python2.6 gets bytes, python3.3 gets string
# so that wsgiref's parsing does not choke

meta_headers = {str("X-DEVPI-API-VERSION"): API_VERSION,
                str("X-DEVPI-SERVER-VERSION"): server_version}

def abort(code, body):
    if "application/json" in request.headers.get("Accept", ""):
        apireturn(code, body)
    error = HTTPError(code, body)
    for n,v in meta_headers.items():
        error.add_header(n, v)
    raise error

def abort_custom(code, msg):
    error = HTTPError(code, msg)
    error.status = "%s %s" %(code, msg)
    raise error

def apireturn(code, message=None, result=None, type=None):
    d = dict() # status=code)
    if result is not None:
        assert type is not None
        d["result"] = result
        d["type"] = type
    if message:
        d["message"] = message
    data = json.dumps(d, indent=2) + "\n"
    header = meta_headers.copy()
    header[str("content-type")] = "application/json"
    raise HTTPResponse(body=data, status=code, header=header)

def json_preferred():
    # XXX do proper "best" matching
    return "application/json" in request.headers.get("Accept", "")

def html_preferred():
    accept = request.headers.get("Accept", "")
    return not accept or "text/html" in accept

route = lazydecorator()

class PyPIView:
    def __init__(self, xom):
        self.xom = xom
        self.db = xom.db
        self.auth = Auth(xom.db, xom.config.secret)

    def getstage(self, user, index):
        stage = self.db.getstage(user, index)
        if not stage:
            abort(404, "no such stage")
        return stage


    #
    # supplying basic API locations for all services
    #

    def get_root_url(self, path):
        assert not path.startswith("/"), path
        url = get_outside_url(request.headers,
                              self.xom.config.args.outside_url)
        return URL(url).addpath(path).url

    @route("/+api")
    @route("/<path:path>/+api")
    def apiconfig_index(self, path=None):
        api = {
            "resultlog": self.get_root_url("+tests"),
            "login": self.get_root_url("+login"),
            "authstatus": self.auth.get_auth_status(request.auth),
        }
        if path:
            parts = path.split("/")
            if len(parts) >= 2:
                user, index = parts[:2]
                ixconfig = self.db.index_get(user, index)
                if not ixconfig:
                    abort(404, "index %s/%s does not exist" %(user, index))
                api.update({
                    "index": self.get_root_url("%s/%s/" % (user, index)),
                    "simpleindex": self.get_root_url("%s/%s/+simple/"
                                                     % (user, index))
                })
                if ixconfig["type"] == "stage":
                    api["pypisubmit"] = self.get_root_url("%s/%s/"
                                                          % (user, index))
        apireturn(200, type="apiconfig", result=api)

    #
    # attachment to release files
    # currently only test results, pending generalization
    #

    @route("/+tests", method="POST")
    def add_attach(self):
        filestore = self.xom.filestore
        data = getjson(request)
        md5 = data["installpkg"]["md5"]
        data = request.body.read()
        if not py.builtin._istext(data):
            data = data.decode("utf-8")
        num = filestore.add_attachment(md5=md5, type="toxresult",
                                       data=data)
        relpath = "/+tests/%s/%s/%s" %(md5, "toxresult", num)
        apireturn(200, type="testresultpath", result=relpath)

    @route("/+tests/<md5>/<type>", method="GET")
    def get_attachlist(self, md5, type):
        filestore = self.xom.filestore
        datalist = list(filestore.iter_attachments(md5=md5, type=type))
        apireturn(200, type="list:toxresult", result=datalist)

    @route("/+tests/<md5>/<type>/<num>", method="GET")
    def get_attach(self, md5, type, num):
        filestore = self.xom.filestore
        data = filestore.get_attachment(md5=md5, type=type, num=num)
        apireturn(200, type="testresult", result=data)

    #
    # index serving and upload
    #

    #@route("/ext/pypi/simple<rest:re:.*>")  # deprecated
    #def extpypi_redirect(self, rest):
    #    redirect("/ext/pypi/+simple%s" % rest)

    @route("/<user>/<index>/+simple/<projectname>")
    @route("/<user>/<index>/+simple/<projectname>/")
    def simple_list_project(self, user, index, projectname):
        # we only serve absolute links so we don't care about the route's slash
        abort_if_invalid_projectname(projectname)
        stage = self.getstage(user, index)
        projectname = ensure_unicode(projectname)
        info = stage.get_project_info(projectname)
        if info and info.name != projectname:
            redirect("/%s/+simple/%s/" % (stage.name, info.name))
        result = stage.getreleaselinks(projectname)
        if isinstance(result, int):
            if result == 404:
                # we don't want pip/easy_install to try the whole simple
                # page -- we know for sure there is no fitting project
                # because all devpi indexes perform package name normalization
                abort(200, "no such project %r" % projectname)
            if result >= 500:
                abort(502, "upstream server has internal error")
            if result < 0:
                abort(502, "upstream server not reachable")
        links = []
        for entry in result:
            relpath = entry.relpath
            href = "/" + relpath
            href = URL(request.path).relpath(href)
            if entry.eggfragment:
                href += "#egg=%s" % entry.eggfragment
            elif entry.md5:
                href += "#md5=%s" % entry.md5
            links.extend([
                 "/".join(relpath.split("/", 2)[:2]) + " ",
                 html.a(entry.basename, href=href),
                 html.br(), "\n",
            ])
        return simple_html_body("%s: links for %s" % (stage.name, projectname),
                                links).unicode(indent=2)

    @route("/<user>/<index>/+simple/")
    def simple_list_all(self, user, index):
        encoding = "utf-8"
        log.info("starting +simple")
        stage = self.getstage(user, index)
        stage_results = []
        for stage, names in stage.op_with_bases("getprojectnames"):
            if isinstance(names, int):
                abort(502, "could not get simple list of %s" % stage.name)
            stage_results.append((stage, names))

        # at this point we are sure we can produce the data without
        # depending on remote networks
        response.content_type = "text/html ; charset=%s" % encoding
        title =  "%s: simple list (including inherited indices)" %(
                 stage.name)
        yield ("<html><head><title>%s</title></head><body><h1>%s</h1>" %(
              title, title)).encode(encoding)
        all_names = set()
        for stage, names in stage_results:
            h2 = stage.name
            bases = getattr(stage, "ixconfig", {}).get("bases")
            if bases:
                h2 += " (bases: %s)" % ",".join(bases)
            yield ("<h2>" + h2 + "</h2>").encode(encoding)
            for name in names:
                if name not in all_names:
                    anchor = '<a href="%s/">%s</a><br/>\n' % (name, name)
                    yield anchor.encode(encoding)
                    all_names.add(name)
        yield "</body>".encode(encoding)

    @route("/<user>/<index>", method=["PUT", "PATCH"])
    def index_create_or_modify(self, user, index):
        self.require_user(user)
        ixconfig = self.db.index_get(user, index)
        if request.method == "PUT" and ixconfig is not None:
            apireturn(409, "index %s/%s exists" % (user, index))
        kvdict = getkvdict_index(getjson(request))
        try:
            if not ixconfig:
                ixconfig = self.db.index_create(user, index, **kvdict)
            else:
                ixconfig = self.db.index_modify(user, index, **kvdict)
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
        ixconfig = self.db.index_get(user, index)
        if not ixconfig:
            apireturn(404, "index %s does not exist" % indexname)
        if not ixconfig["volatile"]:
            apireturn(403, "index %s non-volatile, cannot delete" % indexname)
        assert self.db.index_delete(user, index)
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
        pushdata = getjson(request)
        try:
            name = pushdata["name"]
            version = pushdata["version"]
        except KeyError:
            apireturn(400, message="no name/version specified in json")

        projectconfig = stage.get_projectconfig(name)
        matches = []
        if projectconfig:
            verdata = projectconfig.get(version)
            if verdata:
                files = verdata.get("+files")
                for basename, relpath in files.items():
                    entry = stage.xom.filestore.getentry(relpath)
                    if not entry.iscached():
                        abort(400, "cannot push non-cached files")
                    matches.append(entry)
                metadata = get_pure_metadata(verdata)

        if not matches:
            log.info("%s: no release files %s-%s" %(stage.name, name, version))
            apireturn(404,
                      message="no release/files found for %s-%s" %(
                      name, version))

        doczip = stage.get_doczip(name, version)

        # prepare metadata for submission
        metadata[":action"] = "submit"

        results = []
        targetindex = pushdata.get("targetindex", None)
        if targetindex is not None:
            parts = targetindex.split("/")
            if len(parts) != 2:
                apireturn(400, message="targetindex not in format user/index")
            target_stage = self.getstage(*parts)
            auth_user = self.auth.get_auth_user(request.auth, raising=False)
            log.debug("targetindex %r, auth_user %r", targetindex, auth_user)
            if not target_stage.can_upload(auth_user):
               apireturn(401, message="user %r cannot upload to %r"
                                      %(auth_user, targetindex))
            #results = stage.copy_release(metadata, target_stage)
            #results.append((r.status_code, "upload", entry.relpath))
            #apireturn(200, results=results, type="actionlog")
            if not target_stage.get_metadata(name, version):
                self._register_metadata_dict(target_stage, metadata)
            results.append((200, "register", name, version,
                            "->", target_stage.name))
            for entry in matches:
                res = target_stage.store_releasefile(
                    name, version,
                    entry.basename, entry.FILE.filepath.read(mode="rb"))
                if not isinstance(res, int):
                    res = 200
                results.append((res, "store_releasefile", entry.basename,
                                "->", target_stage.name))
            if doczip:
                target_stage.store_doczip(name, version, doczip)
                results.append((200, "uploaded documentation", name,
                                "->", target_stage.name))
            apireturn(200, result=results, type="actionlog")
        else:
            posturl = pushdata["posturl"]
            username = pushdata["username"]
            password = pushdata["password"]
            pypiauth = (username, password)
            log.info("registering %s-%s to %s", name, version, posturl)
            session = new_requests_session(agent=("server", server_version))
            r = session.post(posturl, data=metadata, auth=pypiauth)
            log.debug("register returned: %s", r.status_code)
            ok_codes = (200, 201)
            results.append((r.status_code, "register", name, version))
            if r.status_code in ok_codes:
                for entry in matches:
                    file_metadata = metadata.copy()
                    file_metadata[":action"] = "file_upload"
                    basename = entry.basename
                    pyver, filetype = get_pyversion_filetype(basename)
                    file_metadata["filetype"] = filetype
                    file_metadata["pyversion"] = pyver
                    openfile = entry.FILE.filepath.open("rb")
                    log.info("sending %s to %s, metadata %s",
                             basename, posturl, file_metadata)
                    r = session.post(posturl, data=file_metadata,
                          auth=pypiauth,
                          files={"content": (basename, openfile)})
                    log.debug("send finished, status: %s", r.status_code)
                    results.append((r.status_code, "upload", entry.relpath,
                                    r.text))
                if doczip:
                    doc_metadata = metadata.copy()
                    doc_metadata[":action"] = "doc_upload"
                    r = session.post(posturl, data=doc_metadata,
                          auth=pypiauth,
                          files={"content": (name + ".zip", doczip)})
                    log.debug("send finished, status: %s", r.status_code)
                    results.append((r.status_code, "docfile", name))
                #
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
            return self._register_metadata_form(stage, request.forms)
        elif action in ("doc_upload", "file_upload"):
            try:
                content = request.files["content"]
            except KeyError:
                abort(400, "content file field not found")
            name = ensure_unicode(request.forms.get("name"))
            version = ensure_unicode(request.forms.get("version"))
            info = stage.get_project_info(name)
            if not info:
                abort(400, "no project named %r was ever registered" %(name))
            if action == "file_upload":
                log.debug("metadata in form: %s", list(request.forms.items()))
                abort_if_invalid_filename(name, content.filename)
                metadata = stage.get_metadata(name, version)
                if not metadata:
                    self._register_metadata_form(stage, request.forms)
                    metadata = stage.get_metadata(name, version)
                    if not metadata:
                        abort_custom(400, "could not process form metadata")
                res = stage.store_releasefile(name, version,
                                              content.filename, content.value)
                if res == 409:
                    abort(409, "%s already exists in non-volatile index" %(
                         content.filename,))
                jenkinurl = stage.ixconfig["uploadtrigger_jenkins"]
                if jenkinurl:
                    jenkinurl = jenkinurl.format(pkgname=name)
                    if trigger_jenkins(stage, jenkinurl, name) == -1:
                        abort_custom(200,
                            "OK, but couldn't trigger jenkins at %s" %
                            (jenkinurl,))
            else:
                # docs have no version (XXX but they are tied to the latest)
                if len(content.value) > MAXDOCZIPSIZE:
                    abort_custom(413, "zipfile size %d too large, max=%s"
                                   % (len(content.value), MAXDOCZIPSIZE))
                stage.store_doczip(name, version,
                                   py.io.BytesIO(content.value))
        else:
            abort(400, "action %r not supported" % action)
        return ""

    def _register_metadata_form(self, stage, form):
        metadata = {}
        for key in stage.metadata_keys:
            if key.lower() in stage.metadata_list_fields:
                val = [ensure_unicode(item)
                        for item in form.getall(key) if item]
            else:
                val = getattr(form, key)  # returns unicode in bottle
                if val == "UNKNOWN":
                    val = ""
                assert py.builtin._istext(val), val
            metadata[key] = val

        self._register_metadata_dict(stage, metadata)

    def _register_metadata_dict(self, stage, metadata):
        try:
            stage.register_metadata(metadata)
        except stage.RegisterNameConflict as e:
            info = e.args[0]
            abort_custom(403, "cannot register %r because %r is already "
                  "registered at %s" % (
                  metadata["name"], info.name, info.stage.name))
        except ValueError as e:
            abort_custom(400, "invalid metadata: %s" % (e,))
        log.info("%s: got submit release info %r",
                 stage.name, metadata["name"])

    #
    #  per-project and version data
    #

    # showing uploaded package documentation
    @route("/<user>/<index>/<name>/<version>/+doc/<relpath:re:.*>",
           method="GET")
    def doc_show(self, user, index, name, version, relpath):
        if not relpath:
            redirect("index.html")
        stage = self.getstage(user, index)
        key = stage._doc_key(name, version)
        if not key.filepath.check():
            abort(404, "no documentation available")
        return static_file(relpath, root=str(key.filepath))

    @route("/<user>/<index>/<name>")
    @route("/<user>/<index>/<name>/")
    def project_get(self, user, index, name):
        #log.debug("HEADERS: %s", request.headers.items())
        stage = self.getstage(user, index)
        name = ensure_unicode(name)
        info = stage.get_project_info(name)
        real_name = info.name if info else name
        if html_preferred():
            # we need to redirect because the simple pages
            # may return status codes != 200, causing
            # pip to look at the full simple list at the parent url
            # but we don't serve this list on /user/index/
            redirect("/%s/+simple/%s/" % (stage.name, real_name))
        if not json_preferred():
            apireturn(415, "unsupported media type %s" %
                      request.headers.items())
        if not info:
            apireturn(404, "project %r does not exist" % name)
        if real_name != name:
            redirect("/%s/%s/" % (stage.name, real_name))
        metadata = stage.get_projectconfig(name)
        apireturn(200, type="projectconfig", result=metadata)

    @route("/<user>/<index>/<name>", method="DELETE")
    @route("/<user>/<index>/<name>/", method="DELETE")
    def project_delete(self, user, index, name):
        self.require_user(user)
        stage = self.getstage(user, index)
        if stage.name == "root/pypi":
            abort(405, "cannot delete root/pypi index")
        if not stage.project_exists(name):
            apireturn(404, "project %r does not exist" % name)
        if not stage.ixconfig["volatile"]:
            apireturn(403, "project %r is on non-volatile index %s" %(
                      name, stage.name))
        stage.project_delete(name)
        apireturn(200, "project %r deleted from stage %s" % (name, stage.name))

    @route("/<user>/<index>/<name>/<version>")
    @route("/<user>/<index>/<name>/<version>/")
    def version_get(self, user, index, name, version):
        stage = self.getstage(user, index)
        name = ensure_unicode(name)
        version = ensure_unicode(version)
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
            if isinstance(value, list):
                value = html.ul([html.li(x) for x in value])
            rows.append(html.tr(html.td(key), html.td(value)))
        title = "%s/: %s-%s metadata and description" % (
                stage.name, name, version)

        content = stage.get_description(name, version)
        #css = "https://pypi.python.org/styles/styles.css"
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
        name = ensure_unicode(name)
        version = ensure_unicode(version)
        if stage.name == "root/pypi":
            abort(405, "cannot delete on root/pypi index")
        if not stage.ixconfig["volatile"]:
            abort(403, "cannot delete version on non-volatile index")
        metadata = stage.get_projectconfig(name)
        if not metadata:
            abort(404, "project %r does not exist" % name)
        verdata = metadata.get(version, None)
        if not verdata:
            abort(404, "version %r does not exist" % version)
        stage.project_version_delete(name, version)
        apireturn(200, "project %r version %r deleted" % (name, version))

    @route("/<user>/<index>/+e/<relpath:re:.*>")
    @route("/<user>/<index>/+f/<relpath:re:.*>")
    def pkgserv(self, user, index, relpath):
        relpath = request.path.strip("/")
        if "#" in relpath:   # XXX unclear how this can happen (it does)
            relpath = relpath.split("#", 1)[0]
        filestore = self.xom.filestore
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
            projectlist = sorted(projectlist)
            apireturn(200, type="list:projectconfig", result=projectlist)
        if stage.name == "root/pypi":
            return simple_html_body("%s index" % stage.name, [
                html.ul(
                    html.li(html.a("simple index", href="+simple/")),
                ),
            ]).unicode()


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
        latest_packages = html.table(
            html.tr(html.td("info"), html.td("file"), html.td("docs")))

        for projectname in stage.getprojectnames_perstage():
            metadata = stage.get_metadata_latest_perstage(projectname)
            try:
                name, ver = metadata["name"], metadata["version"]
            except KeyError:
                log.error("metadata for project %r empty: %s, skipping",
                          projectname, metadata)
                continue
            dockey = stage._doc_key(name, ver)
            if dockey.exists():
                docs = [html.a("%s-%s docs" %(name, ver),
                        href="%s/%s/+doc/index.html" %(name, ver))]
            else:
                docs = []
            files = metadata.get("+files", {})
            if not files:
                log.warn("project %r version %r has no files", projectname,
                         metadata.get("version"))
            baseurl = URL(request.path)
            for basename, relpath in files.items():
                latest_packages.append(html.tr(
                    html.td(html.a("%s-%s info page" % (name, ver),
                           href="%s/%s/" % (name, ver))),
                    html.td(html.a(basename,
                                   href=baseurl.relpath("/" + relpath))),
                    html.td(*docs),
                ))
                break  # could present more releasefiles

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
    def abort_authenticate(self, msg="authentication required"):
        err = HTTPError(401, msg)
        err.add_header(str('WWW-Authenticate'), 'Basic realm="pypi"')
        err.add_header(str('location'), self.get_root_url("+login"))
        raise err

    def require_user(self, user, stage=None, acltype="upload"):
        #log.debug("headers %r", request.headers.items())
        status, auth_user = self.auth.get_auth_status(request.auth)
        log.debug("got auth status %r for user %r" %(status, auth_user))
        if not self.db.user_exists(user):
            abort(404, "required user %r does not exist" % auth_user)
        if status == "nouser":
            abort(404, "user %r does not exist" % auth_user)
        elif status == "expired":
            self.abort_authenticate(msg="auth expired for %r" % auth_user)
        elif status == "noauth":
            self.abort_authenticate()
        if auth_user == "root" or auth_user == user:
            return
        if stage:
            acl = stage.ixconfig.get("acl_" + acltype, [])
            if auth_user in acl:
                log.debug("user %r is acl_upload list", auth_user)
                return
            apireturn(403, message="user %r not authorized for %s to %s"
                             % (auth_user, acltype, stage.name))
        # XXX we should probably never reach here?
        log.info("user %r not authorized", auth_user)
        self.abort_authenticate()


    @route("/+login", method="POST")
    def login(self):
        dict = getjson(request)
        user = dict.get("user", None)
        password = dict.get("password", None)
        #log.debug("got password %r" % password)
        if user is None or password is None:
            abort(400, "Bad request: no user/password specified")
        proxyauth = self.auth.new_proxy_auth(user, password)
        if proxyauth:
            apireturn(200, "login successful", type="proxyauth",
                result=proxyauth)
        apireturn(401, "user %r could not be authenticated" % user)

    @route("/<user>", method="PATCH")
    @route("/<user>/", method="PATCH")
    def user_patch(self, user):
        self.require_user(user)
        dict = getjson(request, allowed_keys=["email", "password"])
        email = dict.get("email")
        password = dict.get("password")
        self.db.user_modify(user, password=password, email=email)
        if password is not None:
            apireturn(200, "user updated, new proxy auth", type="userpassword",
                      result=self.auth.new_proxy_auth(user, password=password))
        apireturn(200, "user updated")

    @route("/<user>", method="PUT")
    def user_create(self, user):
        if self.db.user_exists(user):
            apireturn(409, "user already exists")
        kvdict = getjson(request)
        if "password" in kvdict:  # and "email" in kvdict:
            self.db.user_create(user, **kvdict)
            apireturn(201, type="userconfig", result=self.db.user_get(user))
        apireturn(400, "password needs to be set")

    @route("/<user>", method="DELETE")
    def user_delete(self, user):
        if user == "root":
            apireturn(403, "root user cannot be deleted")
        self.require_user(user)
        userconfig = self.db.user_get(user)
        if not userconfig:
            apireturn(404, "user %r does not exist" % user)
        for name, ixconfig in userconfig.get("indexes", {}).items():
            if not ixconfig["volatile"]:
                apireturn(403, "user %r has non-volatile index: %s" %(
                               user, name))
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


def getjson(request, allowed_keys=None):
    try:
        # request.body is a StringIO on Py2 and a BytesIO on Py3. Convert
        # it to a string, because json doesn't like bytes ...
        content = request.body.read()
        if not py.builtin._istext(content):
            content = content.decode("utf-8")
        dict = json.loads(content)
    except ValueError:
        abort(400, "Bad request: could not decode json")
    if allowed_keys is not None:
        diff = set(dict).difference(allowed_keys)
        if diff:
            abort(400, "json keys not recognized: %s" % ",".join(diff))
    return dict

def get_outside_url(headers, outsideurl):
    if outsideurl:
        url = outsideurl
    else:
        url = headers.get("X-outside-url", None)
        if url is None:
            url = "http://" + headers.get("Host")
    url = url.rstrip("/") + "/"
    log.debug("outside host header: %s", url)
    return url

def trigger_jenkins(stage, jenkinurl, testspec):
    baseurl = get_outside_url(request.headers,
                              stage.xom.config.args.outside_url)

    source = render_string("devpibootstrap.py",
        INDEXURL=baseurl + stage.name,
        VIRTUALENVTARURL= (baseurl +
            "root/pypi/+f/3a04aa2b32c76c83725ed4d9918e362e/"
            "virtualenv-1.10.1.tar.gz"),
        TESTSPEC=testspec,
        DEVPI_INSTALL_INDEX = baseurl + stage.name + "/+simple/"
    )
    inputfile = py.io.BytesIO(source.encode("ascii"))
    req = new_requests_session(agent=("server", server_version))
    try:
        r = req.post(jenkinurl, data={
                        "Submit": "Build",
                        "name": "jobscript.py",
                        "json": json.dumps(
                    {"parameter": {"name": "jobscript.py", "file": "file0"}}),
            },
                files={"file0": ("file0", inputfile)})
    except req.RequestException:
        log.error("%s: failed to connect to jenkins at %s",
                  testspec, jenkinurl)
        return -1

    if 200 <= r.status_code < 300:
        log.info("successfully triggered jenkins: %s", jenkinurl)
    else:
        log.error("%s: failed to trigger jenkins at %s", r.status_code,
                  jenkinurl)
        return -1

def abort_if_invalid_filename(name, filename):
    if not is_valid_archive_name(filename):
        abort_custom(400, "%r is not a valid archive name" %(filename))
    if normalize_name(filename).startswith(normalize_name(name)):
        return
    abort_custom(400, "filename %r does not match project name %r"
                      %(filename, name))

def abort_if_invalid_projectname(projectname):
    try:
        if isinstance(projectname, bytes):
            projectname.decode("ascii")
        else:
            projectname.encode("ascii")
    except (UnicodeEncodeError, UnicodeDecodeError):
        abort(400, "unicode project names not allowed")


def getkvdict_index(req):
    req_volatile = req.get("volatile")
    kvdict = dict(volatile=True, type="stage", bases=["root/pypi"])
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

def get_pure_metadata(somedict):
    metadata = {}
    for n, v in somedict.items():
        if n[0] != "+":
            metadata[n] = v
    return metadata

