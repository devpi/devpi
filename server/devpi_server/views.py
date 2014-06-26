from __future__ import unicode_literals

from copy import deepcopy
import py
from py.xml import html
from devpi_common.types import ensure_unicode
from devpi_common.url import URL
from devpi_common.metadata import get_pyversion_filetype
import devpi_server
from pyramid.compat import urlparse
from pyramid.httpexceptions import HTTPException, HTTPFound, HTTPSuccessful
from pyramid.httpexceptions import exception_response
from pyramid.response import Response
from pyramid.view import view_config
import itertools
import json
from devpi_common.request import new_requests_session
from devpi_common.validation import normalize_name, is_valid_archive_name

from .model import InvalidIndexconfig, _ixconfigattr
from .log import thread_push_log, thread_pop_log, threadlog

from .auth import Auth
from .config import render_string

server_version = devpi_server.__version__


MAXDOCZIPSIZE = 30 * 1024 * 1024    # 30MB


API_VERSION = "1"

# we use str() here so that python2.6 gets bytes, python3.3 gets string
# so that wsgiref's parsing does not choke

meta_headers = {str("X-DEVPI-API-VERSION"): str(API_VERSION),
                str("X-DEVPI-SERVER-VERSION"): server_version}

def abort(request, code, body):
    if "application/json" in request.headers.get("Accept", ""):
        apireturn(code, body)
    raise exception_response(code, body=body, headers=meta_headers)

def abort_custom(code, msg):
    error = type(
        str('HTTPError'), (HTTPException,), dict(
            code=code, title=msg))
    raise error()


def abort_authenticate(request, msg="authentication required"):
    err = type(
        str('HTTPError'), (HTTPException,), dict(
            code=401, title=msg))
    err = err()
    err.headers.add(str('WWW-Authenticate'), str('Basic realm="pypi"'))
    err.headers.add(str('location'), str(request.route_url("/+login")))
    raise err


class HTTPResponse(HTTPSuccessful):
    body_template = None
    comment = None
    detail = None
    def __init__(self, **kw):
        Response.__init__(self, **kw)
        Exception.__init__(self)


def redirect(location):
    raise HTTPFound(location=location)


def apireturn(code, message=None, result=None, type=None):
    d = dict() # status=code)
    if result is not None:
        assert type is not None
        d["result"] = result
        d["type"] = type
    if message:
        d["message"] = message
    data = json.dumps(d, indent=2) + "\n"
    headers = {str("content-type"): str("application/json")}
    raise HTTPResponse(body=data, status=code, headers=headers)

def json_preferred(request):
    # XXX do proper "best" matching
    return "application/json" in request.headers.get("Accept", "")


def route_url(self, *args, **kw):
    xom = self.registry['xom']
    outside_url = get_outside_url(self, xom.config.args.outside_url)
    url = super(self.__class__, self).route_url(
        _app_url=outside_url.rstrip("/"), *args, **kw)
    # Unquote plus signs in path segment. The settings in pyramid for
    # the urllib quoting function are a bit too much on the safe side
    url = urlparse.urlparse(url)
    url = url._replace(path=url.path.replace('%2B', '+'))
    return url.geturl()


def tween_request_logging(handler, registry):
    req_count = itertools.count()
    from time import time

    def request_log_handler(request):
        tag = "[req%s]" %(next(req_count))
        log = thread_push_log(tag)
        request.log = log
        log.info("%s %s" % (request.method, request.path,))
        now = time()
        response = handler(request)
        duration = time() - now
        rheaders = response.headers
        serial = rheaders.get("X-DEVPI-SERIAL")
        rheaders.update(meta_headers)
        log.debug("%s %.3fs serial=%s length=%s type=%s",
                  response.status_code,
                  duration,
                  serial,
                  rheaders.get("content-length"),
                  rheaders.get("content-type"),
        )
        thread_pop_log(tag)
        return response
    return request_log_handler


def tween_keyfs_transaction(handler, registry):
    keyfs = registry["xom"].keyfs
    is_replica = registry["xom"].is_replica()
    def request_tx_handler(request):
        write  = is_mutating_http_method(request.method) and not is_replica
        with keyfs.transaction(write=write) as tx:
            threadlog.debug("in-transaction %s", tx.at_serial)
            response = handler(request)
        serial = tx.commit_serial if tx.commit_serial is not None \
                                  else tx.at_serial
        set_header_devpi_serial(response.headers, serial)
        return response
    return request_tx_handler

def set_header_devpi_serial(headers, serial):
    headers[str("X-DEVPI-SERIAL")] = str(serial)


def is_mutating_http_method(method):
    return method in ("PUT", "POST", "PATCH", "DELETE", "PUSH")


class PyPIView:
    def __init__(self, request):
        self.request = request
        self.context = request.context
        xom = request.registry['xom']
        self.xom = xom
        self.model = xom.model
        self.auth = Auth(self.model, xom.config.secret)
        self.log = request.log

    def get_auth_status(self):
        # this is accessing some pyramid internals, but they are pretty likely
        # to stay and the alternative was uglier
        policy = self.request._get_authentication_policy()
        credentials = policy._get_credentials(self.request)
        return self.auth.get_auth_status(credentials)

    #
    # supplying basic API locations for all services
    #

    @view_config(route_name="/+api")
    @view_config(route_name="{path:.*}/+api")
    def apiconfig_index(self):
        request = self.request
        path = request.matchdict.get('path')
        api = {
            "login": request.route_url('/+login'),
            "authstatus": self.get_auth_status(),
        }
        if path:
            parts = path.split("/")
            if len(parts) >= 2:
                user, index = parts[:2]
                stage = self.context.getstage(user, index)
                api.update({
                    "index": request.route_url(
                        "/{user}/{index}", user=user, index=index),
                    "simpleindex": request.route_url(
                        "/{user}/{index}/+simple/", user=user, index=index)
                })
                if stage.ixconfig["type"] == "stage":
                    api["pypisubmit"] = request.route_url(
                        "/{user}/{index}/", user=user, index=index)
        apireturn(200, type="apiconfig", result=api)

    #
    # attach test results to release files
    #

    @view_config(route_name="/{user}/{index}/+f/{relpath:.*}",
                 request_method="POST")
    def post_toxresult(self):
        stage = self.context.stage
        relpath = self.request.path.strip("/")
        link = stage.get_link_from_entrypath(relpath)
        if link is None or link.rel != "releasefile":
            apireturn(404, message="no release file found at %s" % relpath)
        toxresultdata = getjson(self.request)
        tox_link = stage.store_toxresult(link, toxresultdata)
        apireturn(200, type="toxresultpath",
                  result=tox_link.entrypath)

    #
    # index serving and upload
    #

    @view_config(route_name="/{user}/{index}/+simple/{name}")
    def simple_list_project(self):
        request = self.request
        projectname = self.context.name
        # we only serve absolute links so we don't care about the route's slash
        abort_if_invalid_projectname(request, projectname)
        stage = self.context.stage
        info = stage.get_project_info(projectname)
        if info and info.name != projectname:
            redirect("/%s/+simple/%s/" % (stage.name, info.name))
        result = stage.getreleaselinks(projectname)
        if isinstance(result, int):
            if result == 404:
                # we don't want pip/easy_install to try the whole simple
                # page -- we know for sure there is no fitting project
                # because all devpi indexes perform package name normalization
                abort(request, 200, "no such project %r" % projectname)
            if result >= 500:
                abort(request, 502, "upstream server has internal error")
            if result < 0:
                abort(request, 502, "upstream server not reachable")
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
        title = "%s: links for %s" % (stage.name, projectname)
        return Response(html.html(
            html.head(
                html.title(title)),
            html.body(
                html.h1(title), "\n",
                links)).unicode(indent=2))

    @view_config(route_name="/{user}/{index}/+simple/")
    def simple_list_all(self):
        self.log.info("starting +simple")
        stage = self.context.stage
        stage_results = []
        for stage, names in stage.op_sro("getprojectnames_perstage"):
            if isinstance(names, int):
                abort(self.request, 502,
                      "could not get simple list of %s" % stage.name)
            stage_results.append((stage, names))

        # at this point we are sure we can produce the data without
        # depending on remote networks
        return Response(app_iter=self._simple_list_all(stage, stage_results))

    def _simple_list_all(self, stage, stage_results):
        encoding = "utf-8"
        response = self.request.response
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
                    anchor = '<a href="%s">%s</a><br/>\n' % (name, name)
                    yield anchor.encode(encoding)
                    all_names.add(name)
        yield "</body>".encode(encoding)

    @view_config(
        route_name="/{user}/{index}", request_method="PUT")
    def index_create(self):
        stage = self.context.user.getstage(self.context.index)
        if stage and stage.name == "root/pypi":
            apireturn(403, "root/pypi index config can not be modified")
        if stage is not None:
            apireturn(409, "index %r exists" % stage.name)
        if not self.request.has_permission("index_create"):
            apireturn(403, "no permission to create index %s/%s" % (
                self.context.username, self.context.index))
        kvdict = getkvdict_index(getjson(self.request))
        try:
            stage = self.context.user.create_stage(self.context.index, **kvdict)
            ixconfig = stage.ixconfig
        except InvalidIndexconfig as e:
            apireturn(400, message=", ".join(e.messages))
        apireturn(200, type="indexconfig", result=ixconfig)

    @view_config(
        route_name="/{user}/{index}", request_method="PATCH",
        permission="index_modify")
    def index_modify(self):
        stage = self.context.stage
        if stage.name == "root/pypi":
            apireturn(403, "root/pypi index config can not be modified")
        kvdict = getkvdict_index(getjson(self.request))
        try:
            ixconfig = stage.modify(**kvdict)
        except InvalidIndexconfig as e:
            apireturn(400, message=", ".join(e.messages))
        apireturn(200, type="indexconfig", result=ixconfig)

    @view_config(
        route_name="/{user}/{index}", request_method="DELETE",
        permission="index_delete")
    def index_delete(self):
        stage = self.context.stage
        if not stage.ixconfig["volatile"]:
            apireturn(403, "index %s non-volatile, cannot delete" %
                           stage.name)
        stage.delete()
        apireturn(201, "index %s deleted" % stage.name)

    @view_config(route_name="/{user}/{index}", request_method="PUSH")
    def pushrelease(self):
        request = self.request
        stage = self.context.stage
        pushdata = getjson(request)
        try:
            name = pushdata["name"]
            version = pushdata["version"]
        except KeyError:
            apireturn(400, message="no name/version specified in json")

        vv = stage.get_project_version(name, version)
        matches = [stage.xom.filestore.get_file_entry(link.entrypath)
                        for link in vv.get_links(rel="releasefile")]
        if not matches:
            self.log.info("%s: no release files %s-%s" %(stage.name,
                                                         name, version))
            apireturn(404,
                      message="no release/files found for %s-%s" %(
                      name, version))

        metadata = get_pure_metadata(vv.projectconfig[version])
        doczip = stage.get_doczip(name, version)

        # prepare metadata for submission
        metadata[":action"] = "submit"

        results = []
        targetindex = pushdata.get("targetindex", None)
        if targetindex is not None:
            parts = targetindex.split("/")
            if len(parts) != 2:
                apireturn(400, message="targetindex not in format user/index")
            target_stage = self.context.getstage(*parts)
            auth_user = request.authenticated_userid
            self.log.debug("targetindex %r, auth_user %r", targetindex,
                           auth_user)
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
                    entry.basename, entry.file_get_content())
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
            self.log.info("registering %s-%s to %s", name, version, posturl)
            session = new_requests_session(agent=("server", server_version))
            r = session.post(posturl, data=metadata, auth=pypiauth)
            self.log.debug("register returned: %s", r.status_code)
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
                    content = entry.file_get_content()
                    self.log.info("sending %s to %s, metadata %s",
                             basename, posturl, file_metadata)
                    r = session.post(posturl, data=file_metadata,
                          auth=pypiauth,
                          files={"content": (basename, content)})
                    self.log.debug("send finished, status: %s", r.status_code)
                    results.append((r.status_code, "upload", entry.relpath,
                                    r.text))
                if doczip:
                    doc_metadata = metadata.copy()
                    doc_metadata[":action"] = "doc_upload"
                    r = session.post(posturl, data=doc_metadata,
                          auth=pypiauth,
                          files={"content": (name + ".zip", doczip)})
                    self.log.debug("send finished, status: %s", r.status_code)
                    results.append((r.status_code, "docfile", name))
                #
            if r.status_code in ok_codes:
                apireturn(200, result=results, type="actionlog")
            else:
                apireturn(502, result=results, type="actionlog")

    @view_config(
        route_name="/{user}/{index}/", request_method="POST")
    def submit(self):
        request = self.request
        context = self.context
        if context.username == "root" and context.index == "pypi":
            abort(request, 404, "cannot submit to pypi mirror")
        stage = self.context.stage
        if not request.has_permission("pypi_submit"):
            abort(request, 403, "no permission to submit")
        try:
            action = request.POST[":action"]
        except KeyError:
            abort(request, 400, ":action field not found")
        if action == "submit":
            self._register_metadata_form(stage, request.POST)
            return Response("")
        elif action in ("doc_upload", "file_upload"):
            try:
                content = request.POST["content"]
            except KeyError:
                abort(request, 400, "content file field not found")
            name = ensure_unicode(request.POST.get("name"))
            # version may be empty on plain uploads
            version = ensure_unicode(request.POST.get("version"))
            info = stage.get_project_info(name)
            if not info:
                abort(request, 400, "no project named %r was ever registered" % (name))
            if action == "file_upload":
                self.log.debug("metadata in form: %s",
                               list(request.POST.items()))
                abort_if_invalid_filename(name, content.filename)
                metadata = stage.get_metadata(name, version)
                if not metadata:
                    self._register_metadata_form(stage, request.POST)
                    metadata = stage.get_metadata(name, version)
                    if not metadata:
                        abort_custom(400, "could not process form metadata")
                res = stage.store_releasefile(name, version,
                                              content.filename, content.file.read())
                if res == 409:
                    abort(request, 409, "%s already exists in non-volatile index" % (
                         content.filename,))
                jenkinurl = stage.ixconfig["uploadtrigger_jenkins"]
                if jenkinurl:
                    jenkinurl = jenkinurl.format(pkgname=name)
                    if trigger_jenkins(request, stage, jenkinurl, name) == -1:
                        abort_custom(200,
                            "OK, but couldn't trigger jenkins at %s" %
                            (jenkinurl,))
            else:
                doczip = content.file.read()
                if len(doczip) > MAXDOCZIPSIZE:
                    abort_custom(413, "zipfile size %d too large, max=%s"
                                   % (len(doczip), MAXDOCZIPSIZE))
                stage.store_doczip(name, version, doczip)
        else:
            abort(request, 400, "action %r not supported" % action)
        return Response("")

    def _register_metadata_form(self, stage, form):
        metadata = {}
        for key in stage.metadata_keys:
            if key.lower() in stage.metadata_list_fields:
                val = [ensure_unicode(item)
                        for item in form.getall(key) if item]
            else:
                val = form.get(key, "")
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
        self.log.info("%s: got submit release info %r",
                 stage.name, metadata["name"])

    #
    #  per-project and version data
    #

    @view_config(route_name="simple_redirect")
    def simple_redirect(self):
        stage, name = self.context.stage, self.context.name
        info = stage.get_project_info(name)
        real_name = info.name if info else name
        redirect("/%s/+simple/%s" % (stage.name, real_name))

    @view_config(route_name="/{user}/{index}/{name}", accept="application/json", request_method="GET")
    def project_get(self):
        request = self.request
        #self.log.debug("HEADERS: %s", request.headers.items())
        stage, name = self.context.stage, self.context.name
        info = stage.get_project_info(name)
        real_name = info.name if info else name
        if not json_preferred(request):
            apireturn(415, "unsupported media type %s" %
                      request.headers.items())
        if not info:
            apireturn(404, "project %r does not exist" % name)
        if real_name != name:
            redirect("/%s/%s" % (stage.name, real_name))
        view_metadata = {}
        for version, verdata in stage.get_projectconfig(name).items():
            view_verdata = self._make_view_verdata(verdata)
            view_metadata[version] = view_verdata
        apireturn(200, type="projectconfig", result=view_metadata)

    @view_config(
        route_name="/{user}/{index}/{name}", request_method="DELETE",
        permission="project_delete")
    def project_delete(self):
        stage, name = self.context.stage, self.context.name
        if stage.name == "root/pypi":
            abort(self.request, 405, "cannot delete root/pypi index")
        if not stage.project_exists(name):
            apireturn(404, "project %r does not exist" % name)
        if not stage.ixconfig["volatile"]:
            apireturn(403, "project %r is on non-volatile index %s" %(
                      name, stage.name))
        stage.project_delete(name)
        apireturn(200, "project %r deleted from stage %s" % (name, stage.name))

    @view_config(route_name="/{user}/{index}/{name}/{version}", accept="application/json", request_method="GET")
    def version_get(self):
        stage = self.context.stage
        name, version = self.context.name, self.context.version
        metadata = stage.get_projectconfig(name)
        if not metadata:
            abort(self.request, 404, "project %r does not exist" % name)
        verdata = metadata.get(version, None)
        if not verdata:
            abort(self.request, 404, "version %r does not exist" % version)

        view_verdata = self._make_view_verdata(verdata)
        apireturn(200, type="versiondata", result=view_verdata)

    def _make_view_verdata(self, verdata):
        view_verdata = deepcopy(verdata)
        elinks = view_verdata.pop("+elinks", None)
        if elinks is not None:
            view_verdata["+links"] = links = []
            for elinkdict in elinks:
                linkdict = deepcopy(elinkdict)
                entrypath = linkdict.pop("entrypath")
                linkdict["href"] = self._url_for_entrypath(entrypath)
                for_entrypath = linkdict.pop("for_entrypath", None)
                if for_entrypath is not None:
                    linkdict["for_href"] = \
                        self._url_for_entrypath(for_entrypath)
                links.append(linkdict)
        return view_verdata

    def _url_for_entrypath(self, entrypath):
        parts = entrypath.split("/")
        user, index = parts[:2]
        assert parts[2] in ("+f", "+e")
        route_name = "/{user}/{index}/%s/{relpath:.*}" % parts[2]
        relpath = "/".join(parts[3:])
        return self.request.route_url(
               route_name, user=user, index=index, relpath=relpath)

    @view_config(route_name="/{user}/{index}/{name}/{version}", request_method="DELETE")
    def project_version_delete(self):
        stage = self.context.stage
        name, version = self.context.name, self.context.version
        if stage.name == "root/pypi":
            abort(self.request, 405, "cannot delete on root/pypi index")
        if not stage.ixconfig["volatile"]:
            abort(self.request, 403, "cannot delete version on non-volatile index")
        metadata = stage.get_projectconfig(name)
        if not metadata:
            abort(self.request, 404, "project %r does not exist" % name)
        verdata = metadata.get(version, None)
        if not verdata:
            abort(self.request, 404, "version %r does not exist" % version)
        stage.project_version_delete(name, version)
        apireturn(200, "project %r version %r deleted" % (name, version))

    @view_config(route_name="/{user}/{index}/+e/{relpath:.*}")
    @view_config(route_name="/{user}/{index}/+f/{relpath:.*}")
    def pkgserv(self):
        request = self.request
        relpath = request.path.strip("/")
        if "#" in relpath:   # XXX unclear how this happens (did with bottle)
            relpath = relpath.split("#", 1)[0]
        filestore = self.xom.filestore
        entry = filestore.get_file_entry(relpath)
        if json_preferred(request):
            if not entry or not entry.meta:
                apireturn(404, "no such release file")
            apireturn(200, type="releasefilemeta", result=entry.meta)
        if not entry or not entry.meta:
            abort(request, 404, "no such file")

        if not entry.file_exists() or entry.eggfragment:
            keyfs = self.xom.keyfs
            if not self.xom.is_replica():
                keyfs.restart_as_write_transaction()
                entry = filestore.get_file_entry(relpath)
                entry.cache_remote_file()
            else:
                entry = entry.cache_remote_file_replica()

        headers = entry.gethttpheaders()
        if self.request.method == "HEAD":
            return Response(headers=headers)
        else:
            content = entry.file_get_content()
            return Response(body=content, headers=headers)

    @view_config(route_name="/{user}/{index}", accept="application/json", request_method="GET")
    def index_get(self):
        stage = self.context.stage
        result = dict(stage.ixconfig)
        result['projects'] = sorted(stage.getprojectnames_perstage())
        apireturn(200, type="indexconfig", result=result)

    #
    # login and user handling
    #
    @view_config(route_name="/+login", request_method="POST")
    def login(self):
        request = self.request
        dict = getjson(request)
        user = dict.get("user", None)
        password = dict.get("password", None)
        #self.log.debug("got password %r" % password)
        if user is None or password is None:
            abort(request, 400, "Bad request: no user/password specified")
        proxyauth = self.auth.new_proxy_auth(user, password)
        if proxyauth:
            apireturn(200, "login successful", type="proxyauth",
                result=proxyauth)
        apireturn(401, "user %r could not be authenticated" % user)

    @view_config(
        route_name="/{user}", request_method="PATCH",
        permission="user_modify")
    def user_patch(self):
        request = self.request
        dict = getjson(request, allowed_keys=["email", "password"])
        email = dict.get("email")
        password = dict.get("password")
        user = self.context.user
        user.modify(password=password, email=email)
        if password is not None:
            apireturn(200, "user updated, new proxy auth",
                      type="userpassword",
                      result=self.auth.new_proxy_auth(user.name,
                                                      password=password))
        apireturn(200, "user updated")

    @view_config(route_name="/{user}", request_method="PUT")
    def user_create(self):
        username = self.context.username
        request = self.request
        user = self.model.get_user(username)
        if user is not None:
            apireturn(409, "user already exists")
        kvdict = getjson(request)
        if "password" in kvdict:  # and "email" in kvdict:
            user = self.model.create_user(username, **kvdict)
            apireturn(201, type="userconfig", result=user.get())
        apireturn(400, "password needs to be set")

    @view_config(
        route_name="/{user}", request_method="DELETE",
        permission="user_delete")
    def user_delete(self):
        context = self.context
        if not context.user:
            abort(self.request, 404, "required user %r does not exist" % context.username)
        userconfig = context.user.get()
        if not userconfig:
            apireturn(404, "user %r does not exist" % context.username)
        for name, ixconfig in userconfig.get("indexes", {}).items():
            if not ixconfig["volatile"]:
                apireturn(403, "user %r has non-volatile index: %s" %(
                               context.username, name))
        context.user.delete()
        apireturn(200, "user %r deleted" % context.username)

    @view_config(route_name="/{user}", accept="application/json", request_method="GET")
    def user_get(self):
        if self.context.user is None:
            apireturn(404, "user %r does not exist" % self.context.username)
        userconfig = self.context.user.get()
        apireturn(200, type="userconfig", result=userconfig)

    @view_config(route_name="/", accept="application/json", request_method="GET")
    def user_list(self):
        #accept = request.headers.get("accept")
        #if accept is not None:
        #    if accept.endswith("/json"):
        d = {}
        for user in self.model.get_userlist():
            d[user.name] = user.get()
        apireturn(200, type="list:userconfig", result=d)


def getjson(request, allowed_keys=None):
    try:
        dict = request.json_body
    except ValueError:
        abort(request, 400, "Bad request: could not decode json")
    if allowed_keys is not None:
        diff = set(dict).difference(allowed_keys)
        if diff:
            abort(request, 400, "json keys not recognized: %s" % ",".join(diff))
    return dict

def get_outside_url(request, outsideurl):
    if outsideurl:
        url = outsideurl
    else:
        url = request.headers.get("X-outside-url", None)
        if url is None:
            url = request.application_url
    url = url.rstrip("/") + "/"
    #self.log.debug("outside host header: %s", url)
    return url

def trigger_jenkins(request, stage, jenkinurl, testspec):
    log = request.log
    baseurl = get_outside_url(request, stage.xom.config.args.outside_url)

    source = render_string("devpibootstrap.py",
        INDEXURL=baseurl + stage.name,
        VIRTUALENVTARURL= (baseurl +
            "root/pypi/+f/d3d/915836c1ada1be731ccaa12412b98/"
            "virtualenv-1.11.2.tar.gz",
            ),
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
        log.debug(r.content)
        return -1

def abort_if_invalid_filename(name, filename):
    if not is_valid_archive_name(filename):
        abort_custom(400, "%r is not a valid archive name" %(filename))
    if normalize_name(filename).startswith(normalize_name(name)):
        return
    abort_custom(400, "filename %r does not match project name %r"
                      %(filename, name))

def abort_if_invalid_projectname(request, projectname):
    try:
        if isinstance(projectname, bytes):
            projectname.decode("ascii")
        else:
            projectname.encode("ascii")
    except (UnicodeEncodeError, UnicodeDecodeError):
        abort(request, 400, "unicode project names not allowed")


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
    additional_keys = _ixconfigattr - set(('volatile', 'bases'))
    for key in additional_keys:
        if key in req:
            kvdict[key] = req[key]
    return kvdict

def get_pure_metadata(somedict):
    metadata = {}
    for n, v in somedict.items():
        if n[0] != "+":
            metadata[n] = v
    return metadata

