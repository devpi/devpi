from __future__ import unicode_literals

import os
import py
from py.xml import html
from devpi_common.types import ensure_unicode
from devpi_common.url import URL
from devpi_common.metadata import get_pyversion_filetype
import devpi_server
from pyramid.compat import urlparse
from pyramid.httpexceptions import HTTPException, HTTPFound, HTTPSuccessful
from pyramid.httpexceptions import HTTPUnauthorized
from pyramid.httpexceptions import exception_response
from pyramid.response import Response
from pyramid.security import forget
from pyramid.view import view_config
import itertools
import json
from devpi_common.request import new_requests_session
from devpi_common.validation import normalize_name, is_valid_archive_name

from .model import InvalidIndexconfig, InvalidUser, _ixconfigattr
from .keyfs import copy_if_mutable
from .log import thread_push_log, thread_pop_log, threadlog

from .auth import Auth
from .config import render_string

server_version = devpi_server.__version__


H_MASTER_UUID = str("X-DEVPI-MASTER-UUID")


API_VERSION = "2"

# we use str() here so that python2.6 gets bytes, python3.3 gets string
# so that wsgiref's parsing does not choke

meta_headers = {str("X-DEVPI-API-VERSION"): str(API_VERSION),
                str("X-DEVPI-SERVER-VERSION"): server_version}

def abort(request, code, body):
    # if no Accept header is set, then force */*, otherwise the exception
    # will be returned as text/plain, which causes easy_install/setuptools
    # to fail improperly
    request.headers.setdefault("Accept", "*/*")
    if "application/json" in request.headers.get("Accept", ""):
        apireturn(code, body)
    threadlog.error(body)
    raise exception_response(code, explanation=body, headers=meta_headers)

def abort_submit(code, msg):
    # we construct our own type because we need to set the title
    # so that setup.py upload/register use it to explain the failure
    error = type(
        str('HTTPError'), (HTTPException,), dict(
            code=code, title=msg))
    threadlog.error(msg)
    raise error(headers=meta_headers)


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


class OutsideURLMiddleware(object):
    def __init__(self, app, xom):
        self.app = app
        self.xom = xom

    def __call__(self, environ, start_response):
        outside_url = self.xom.config.args.outside_url
        if not outside_url:
            outside_url = environ.get('HTTP_X_OUTSIDE_URL')
        if outside_url:
            # XXX memoize it for later access from replica thread
            # self.xom.current_outside_url = outside_url
            outside_url = urlparse.urlparse(outside_url)
            environ['wsgi.url_scheme'] = outside_url.scheme
            environ['HTTP_HOST'] = outside_url.netloc
            if outside_url.path:
                environ['SCRIPT_NAME'] = outside_url.path
        return self.app(environ, start_response)


def route_url(self, *args, **kw):
    url = super(self.__class__, self).route_url(*args, **kw)
    # Unquote plus signs in path segment. The settings in pyramid for
    # the urllib quoting function are a bit too much on the safe side
    url = urlparse.urlparse(url)
    url = url._replace(path=url.path.replace('%2B', '+'))
    return url.geturl()


def tween_request_logging(handler, registry):
    req_count = itertools.count()
    from time import time

    nodeinfo = registry["xom"].config.nodeinfo

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
        uuid, master_uuid = make_uuid_headers(nodeinfo)
        rheaders[str("X-DEVPI-UUID")] = str(uuid)
        rheaders[H_MASTER_UUID] = str(master_uuid)

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


def make_uuid_headers(nodeinfo):
    uuid = master_uuid = nodeinfo.get("uuid")
    if uuid is not None and nodeinfo["role"] == "replica":
        master_uuid = nodeinfo.get("master-uuid", "")
    return uuid, master_uuid


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

class StatusView:
    def __init__(self, request):
        self.request = request
        self.xom = request.registry["xom"]

    @view_config(route_name="/+status")
    def status(self):
        config = self.xom.config

        status = {
            "serverdir": str(config.serverdir),
            "uuid": self.xom.config.nodeinfo["uuid"],
            "versioninfo":
                    dict(self.request.registry["devpi_version_info"]),
            "server-code": os.path.dirname(devpi_server.__file__),
            "host": config.args.host,
            "port": config.args.port,
            "outside-url": config.args.outside_url,
            "serial": self.xom.keyfs.get_current_serial(),
            "event-serial": self.xom.keyfs.notifier.read_event_serial(),
        }
        master_url = config.args.master_url
        if master_url:
            from .replica import ReplicationErrors
            status["role"] = "REPLICA"
            status["master-url"] = master_url
            status["master-uuid"] = config.nodeinfo.get("master-uuid")
            replication_errors = ReplicationErrors(self.xom.config.serverdir)
            status["replication-errors"] = replication_errors.errors
        else:
            status["role"] = "MASTER"
        status["polling_replicas"] = self.xom.polling_replicas
        apireturn(200, type="status", result=status)


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
        if self.xom.is_replica():
            from .replica import proxy_request_to_master
            r = proxy_request_to_master(self.xom, self.request)
            if r.status_code == 200:
                return r.json()["result"]["authstatus"]
            threadlog.error("could not obtain master authentication status")
            return ["fail", "", []]
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
                    "index": request.stage_url(stage),
                    "simpleindex": request.simpleindex_url(stage)
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
        relpath = self.request.path_info.strip("/")
        link = stage.get_link_from_entrypath(relpath)
        if link is None or link.rel != "releasefile":
            apireturn(404, message="no release file found at %s" % relpath)
        toxresultdata = getjson(self.request)
        tox_link = stage.store_toxresult(link, toxresultdata)
        tox_link.add_log(
            'upload', self.request.authenticated_userid, dst=stage.name)
        apireturn(200, type="toxresultpath",
                  result=tox_link.entrypath)

    #
    # index serving and upload
    #

    @view_config(route_name="/{user}/{index}/+simple/{name}")
    def simple_list_project(self):
        request = self.request
        name = self.context.name
        # we only serve absolute links so we don't care about the route's slash
        abort_if_invalid_projectname(request, name)
        stage = self.context.stage
        if stage.get_projectname(name) is None:
            # we return 200 instead of !=200 so that pip/easy_install don't
            # ask for the full simple page although we know it doesn't exist
            # XXX change that when pip-6.0 is released?
            abort(request, 200, "no such project %r" % name)

        projectname = self.context.projectname
        try:
            result = stage.get_releaselinks(projectname)
        except stage.UpstreamError as e:
            threadlog.error(e.msg)
            abort(request, 502, e.msg)
        links = []
        for link in result:
            relpath = link.entrypath
            href = "/" + relpath
            href = URL(request.path_info).relpath(href)
            if link.eggfragment:
                href += "#egg=%s" % link.eggfragment
            elif link.hash_spec:
                href += "#" + link.hash_spec
            links.extend([
                 "/".join(relpath.split("/", 2)[:2]) + " ",
                 html.a(link.basename, href=href),
                 html.br(), "\n",
            ])
        title = "%s: links for %s" % (stage.name, projectname)
        if stage.has_pypi_base(projectname):
            refresh_title = "Refresh" if stage.ixconfig["type"] == "mirror" else \
                            "Refresh PyPI links"
            refresh_url = request.route_url(
                "/{user}/{index}/+simple/{name}/refresh",
                user=self.context.username, index=self.context.index,
                name=projectname)
            refresh_form = [
                html.form(
                    html.input(
                        type="submit", value=refresh_title, name="refresh"),
                    action=refresh_url,
                    method="post"),
                "\n"]
        else:
            refresh_form = []
        return Response(html.html(
            html.head(
                html.title(title)),
            html.body(
                html.h1(title), "\n",
                refresh_form,
                links)).unicode(indent=2))

    @view_config(route_name="/{user}/{index}/+simple/")
    def simple_list_all(self):
        self.log.info("starting +simple")
        stage = self.context.stage
        try:
            stage_results = list(stage.op_sro("list_projectnames_perstage"))
        except stage.UpstreamError as e:
            threadlog.error(e.msg)
            abort(self.request, 502, e.msg)
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
            for name in sorted(names):
                if name not in all_names:
                    anchor = '<a href="%s">%s</a><br/>\n' % (name, name)
                    yield anchor.encode(encoding)
                    all_names.add(name)
        yield "</body>".encode(encoding)

    @view_config(
        route_name="/{user}/{index}/+simple/{name}/refresh", request_method="POST")
    def simple_refresh(self):
        context = self.context
        stage = context.model.getstage('root', 'pypi')
        if stage.ixconfig["type"] == "mirror":
            stage.clear_cache(context.name)
        redirect(self.request.route_url(
            "/{user}/{index}/+simple/{name}",
            user=context.username, index=context.index, name=context.name))

    @view_config(
        route_name="/{user}/{index}", request_method="PUT")
    def index_create(self):
        stage = self.context.user.getstage(self.context.index)
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

        # first, get all the links related to the source "to push" release
        try:
            linkstore = stage.get_linkstore_perstage(name, version)
        except stage.MissesRegistration:
            apireturn(400, "there are no files for %s-%s on stage %s" %(
                           name, version, stage.name))
        links = dict([(rel, linkstore.get_links(rel=rel))
                        for rel in ('releasefile', 'doczip', 'toxresult')])
        if not links["releasefile"]:
            self.log.info("%s: no release files for version %s-%s" %
                          (stage.name, name, version))
            apireturn(404, message="no release/files found for %s-%s" %(
                      name, version))

        metadata = get_pure_metadata(linkstore.verdata)

        results = []
        targetindex = pushdata.get("targetindex", None)
        if targetindex is not None:  # in-server push
            parts = targetindex.split("/")
            if len(parts) != 2:
                apireturn(400, message="targetindex not in format user/index")
            target_stage = self.context.getstage(*parts)
            auth_user = request.authenticated_userid
            self.log.debug("targetindex %r, auth_user %r", targetindex,
                           auth_user)
            if not request.has_permission("pypi_submit", context=target_stage):
               apireturn(401, message="user %r cannot upload to %r"
                                      %(auth_user, targetindex))
            self._set_versiondata_dict(target_stage, metadata)
            results.append((200, "register", name, version,
                            "->", target_stage.name))
            try:
                results.extend(self._push_links(links, target_stage, name, version))
            except target_stage.NonVolatile as e:
                apireturn(409, "%s already exists in non-volatile index" % (
                          e.link.basename,))
            apireturn(200, result=results, type="actionlog")
        else:
            posturl = pushdata["posturl"]
            username = pushdata["username"]
            password = pushdata["password"]
            pypiauth = (username, password)
            # prepare metadata for submission
            metadata[":action"] = "submit"
            self.log.info("registering %s-%s to %s", name, version, posturl)
            session = new_requests_session(agent=("server", server_version))
            r = session.post(posturl, data=metadata, auth=pypiauth)
            self.log.debug("register returned: %s", r.status_code)
            ok_codes = (200, 201)
            results.append((r.status_code, "register", name, version))
            if r.status_code in ok_codes:
                for link in links["releasefile"]:
                    entry = link.entry
                    file_metadata = metadata.copy()
                    file_metadata[":action"] = "file_upload"
                    basename = link.basename
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
                if links["doczip"]:
                    doc_metadata = metadata.copy()
                    doc_metadata[":action"] = "doc_upload"
                    doczip = links["doczip"][0].entry.file_get_content()
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

    def _push_links(self, links, target_stage, name, version):
        for link in links["releasefile"]:
            new_link = target_stage.store_releasefile(
                name, version, link.basename, link.entry.file_get_content(),
                last_modified=link.entry.last_modified)
            new_link.add_logs(
                x for x in link.get_logs()
                if x.get('what') != 'overwrite')
            new_link.add_log(
                'push',
                self.request.authenticated_userid,
                src=self.context.stage.name,
                dst=target_stage.name)
            entry = new_link.entry
            yield (200, "store_releasefile", entry.relpath)
            # also store all dependent tox results
            tstore = target_stage.get_linkstore_perstage(name, version)
            for toxlink in links["toxresult"]:
                if toxlink.for_entrypath == link.entry.relpath:
                    ref_link = tstore.get_links(entrypath=entry.relpath)[0]
                    raw_data = toxlink.entry.file_get_content()
                    data = json.loads(raw_data.decode("utf-8"))
                    tlink = target_stage.store_toxresult(ref_link, data)
                    tlink.add_logs(
                        x for x in toxlink.get_logs()
                        if x.get('what') != 'overwrite')
                    tlink.add_log(
                        'push',
                        self.request.authenticated_userid,
                        src=self.context.stage.name,
                        dst=target_stage.name)
                    yield (200, "store_toxresult", tlink.entrypath)
        for link in links["doczip"]:
            doczip = link.entry.file_get_content()
            new_link = target_stage.store_doczip(name, version, doczip)
            new_link.add_logs(link.get_logs())
            new_link.add_log(
                'push',
                self.request.authenticated_userid,
                src=self.context.stage.name,
                dst=target_stage.name)
            yield (200, "store_doczip", name, version,
                   "->", target_stage.name)
            break # we only can have one doczip for now

    @view_config(
        route_name="/{user}/{index}/", request_method="POST")
    def submit(self):
        request = self.request
        context = self.context
        if context.username == "root" and context.index == "pypi":
            abort_submit(404, "cannot submit to pypi mirror")
        stage = self.context.stage
        if not request.has_permission("pypi_submit"):
            # if there is no authenticated user, then issue a basic auth challenge
            if not request.authenticated_userid:
                response = HTTPUnauthorized()
                response.headers.update(forget(request))
                return response
            abort_submit(403, "no permission to submit")
        try:
            action = request.POST[":action"]
        except KeyError:
            abort_submit(400, ":action field not found")
        if action == "submit":
            self._set_versiondata_form(stage, request.POST)
            return Response("")
        elif action in ("doc_upload", "file_upload"):
            try:
                content = request.POST["content"]
            except KeyError:
                abort_submit(400, "content file field not found")
            name = ensure_unicode(request.POST.get("name"))
            # version may be empty on plain uploads
            version = ensure_unicode(request.POST.get("version") or "")
            projectname = stage.get_projectname(name)
            if projectname is None:
                abort_submit(400, "no project named %r was ever registered" % (name))
            if action == "file_upload":
                self.log.debug("metadata in form: %s",
                               list(request.POST.items()))
                abort_if_invalid_filename(name, content.filename)
                metadata = stage.get_versiondata_perstage(projectname, version)
                if not metadata:
                    self._set_versiondata_form(stage, request.POST)
                    metadata = stage.get_versiondata(projectname, version)
                    if not metadata:
                        abort_submit(400, "could not process form metadata")
                file_content = content.file.read()
                try:
                    link = stage.store_releasefile(
                        projectname, version,
                        content.filename, file_content)
                except stage.NonVolatile as e:
                    if e.link.matches_checksum(file_content):
                        abort_submit(200,
                            "Upload of identical file to non volatile index.")
                    abort_submit(409, "%s already exists in non-volatile index" % (
                         content.filename,))
                link.add_log(
                    'upload', request.authenticated_userid, dst=stage.name)
                jenkinurl = stage.ixconfig["uploadtrigger_jenkins"]
                if jenkinurl:
                    jenkinurl = jenkinurl.format(pkgname=name,
                                                 pkgversion=version)
                    if trigger_jenkins(request, stage, jenkinurl, name) == -1:
                        abort_submit(200,
                            "OK, but couldn't trigger jenkins at %s" %
                            (jenkinurl,))
            else:
                doczip = content.file.read()
                try:
                    link = stage.store_doczip(projectname, version, doczip)
                except stage.MissesRegistration:
                    apireturn(400, "%s-%s is not registered" %(name, version))
                except stage.NonVolatile as e:
                    if e.link.matches_checksum(doczip):
                        abort_submit(200,
                            "Upload of identical file to non volatile index.")
                    abort_submit(409, "%s already exists in non-volatile index" % (
                         content.filename,))
                link.add_log(
                    'upload', request.authenticated_userid, dst=stage.name)
        else:
            abort_submit(400, "action %r not supported" % action)
        return Response("")

    def _set_versiondata_form(self, stage, form):
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

        self._set_versiondata_dict(stage, metadata)

    def _set_versiondata_dict(self, stage, metadata):
        try:
            stage.set_versiondata(metadata)
        except ValueError as e:
            abort_submit(400, "invalid metadata: %s" % (e,))
        self.log.info("%s: got submit release info %r",
                 stage.name, metadata["name"])

    #
    #  per-project and version data
    #

    @view_config(route_name="simple_redirect")
    def simple_redirect(self):
        stage, name = self.context.stage, self.context.name
        projectname = stage.get_projectname(name)
        real_name = projectname if projectname else name
        redirect("/%s/+simple/%s" % (stage.name, real_name))

    @view_config(route_name="/{user}/{index}/{name}",
                 accept="application/json", request_method="GET")
    def project_get(self):
        if not json_preferred(self.request):
            apireturn(415, "unsupported media type %s" %
                      self.request.headers.items())
        context = self.context
        view_metadata = {}
        for version in context.list_versions():
            view_metadata[version] = self._make_view_verdata(
                context.get_versiondata(version=version))
        apireturn(200, type="projectconfig", result=view_metadata)

    @view_config(
        route_name="/{user}/{index}/{name}", request_method="DELETE",
        permission="del_project")
    def del_project(self):
        stage = self.context.stage
        if stage.name == "root/pypi":
            abort(self.request, 405, "cannot delete root/pypi index")
        projectname = self.context.projectname
        if not stage.ixconfig["volatile"]:
            apireturn(403, "project %r is on non-volatile index %s" %(
                      projectname, stage.name))
        stage.del_project(projectname)
        apireturn(200, "project {name} deleted from stage {sname}".format(
                  name=projectname, sname=stage.name))

    @view_config(route_name="/{user}/{index}/{name}/{version}", accept="application/json", request_method="GET")
    def version_get(self):
        verdata = self.context.get_versiondata(perstage=False)
        view_verdata = self._make_view_verdata(verdata)
        apireturn(200, type="versiondata", result=view_verdata)

    def _make_view_verdata(self, verdata):
        view_verdata = copy_if_mutable(verdata)
        elinks = view_verdata.pop("+elinks", None)
        if elinks is not None:
            view_verdata["+links"] = links = []
            for elinkdict in elinks:
                linkdict = copy_if_mutable(elinkdict)
                entrypath = linkdict.pop("entrypath")
                linkdict["href"] = url_for_entrypath(self.request, entrypath)
                for_entrypath = linkdict.pop("for_entrypath", None)
                if for_entrypath is not None:
                    linkdict["for_href"] = \
                        url_for_entrypath(self.request, for_entrypath)
                if "_log" in linkdict:
                    linkdict["log"] = list(linkdict.pop("_log"))
                links.append(linkdict)
        shadowing = view_verdata.pop("+shadowing", None)
        if shadowing:
            view_verdata["+shadowing"] = \
                    [self._make_view_verdata(x) for x in shadowing]
        return view_verdata

    @view_config(route_name="/{user}/{index}/{name}/{version}",
                 permission="del_verdata",
                 request_method="DELETE")
    def del_versiondata(self):
        stage = self.context.stage
        name, version = self.context.name, self.context.version
        if stage.name == "root/pypi":
            abort(self.request, 405, "cannot delete on root/pypi index")
        if not stage.ixconfig["volatile"]:
            abort(self.request, 403, "cannot delete version on non-volatile index")
        try:
            stage.del_versiondata(name, version)
        except stage.NotFound as e:
            abort(self.request, 404, e.msg)
        apireturn(200, "project %r version %r deleted" % (name, version))

    @view_config(route_name="/{user}/{index}/+e/{relpath:.*}")
    @view_config(route_name="/{user}/{index}/+f/{relpath:.*}")
    def pkgserv(self):
        request = self.request
        relpath = request.path_info.strip("/")
        if "#" in relpath:   # XXX unclear how this happens (did with bottle)
            relpath = relpath.split("#", 1)[0]
        filestore = self.xom.filestore
        entry = filestore.get_file_entry(relpath)
        if json_preferred(request):
            if not entry or not entry.meta:
                apireturn(404, "no such release file")
            apireturn(200, type="releasefilemeta", result=entry.meta)
        if not entry or not entry.meta:
            if entry is None:
                abort(request, 404, "no such file")
            else:
                abort(request, 410, "file existed, deleted in later serial")

        if should_fetch_remote_file(entry, request.headers):
            keyfs = self.xom.keyfs
            try:
                if not self.xom.is_replica():
                    keyfs.restart_as_write_transaction()
                    entry = filestore.get_file_entry(relpath)
                    entry.cache_remote_file()
                else:
                    entry = entry.cache_remote_file_replica()
            except entry.BadGateway as e:
                return apireturn(502, e.args[0])

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
        result['projects'] = sorted(stage.list_projectnames_perstage())
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

    @view_config(
        route_name="/{user}", request_method="PUT",
        permission="user_create")
    def user_create(self):
        username = self.context.username
        request = self.request
        user = self.model.get_user(username)
        if user is not None:
            apireturn(409, "user already exists")
        kvdict = getjson(request)
        if "password" in kvdict:  # and "email" in kvdict:
            try:
                user = self.model.create_user(username, **kvdict)
            except InvalidUser as e:
                apireturn(400, "%s" % e)
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


def should_fetch_remote_file(entry, headers):
    from .replica import H_REPLICA_FILEREPL
    should_fetch = not entry.file_exists()
    # if we are asked for an "egg" development link we cause
    # refetching it unless we are called within file replication context
    if entry.eggfragment and not headers.get(H_REPLICA_FILEREPL):
        should_fetch = True
    return should_fetch


def url_for_entrypath(request, entrypath):
    parts = entrypath.split("/")
    user, index = parts[:2]
    assert parts[2] in ("+f", "+e")
    route_name = "/{user}/{index}/%s/{relpath:.*}" % parts[2]
    relpath = "/".join(parts[3:])
    return request.route_url(
        route_name, user=user, index=index, relpath=relpath)


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

def trigger_jenkins(request, stage, jenkinurl, testspec):
    log = request.log
    baseurl = request.application_url

    source = render_string("devpibootstrap.py",
        INDEXURL=baseurl + "/" + stage.name,
        VIRTUALENVTARURL= (baseurl +
            "/root/pypi/+f/f61/cdd983d2c4e6a/"
            "virtualenv-1.11.6.tar.gz"
            ),
        TESTSPEC=testspec,
        DEVPI_INSTALL_INDEX = baseurl + "/" + stage.name + "/+simple/"
    )
    inputfile = py.io.BytesIO(source.encode("ascii"))
    session = new_requests_session(agent=("server", server_version))
    try:
        r = session.post(jenkinurl, data={
                        "Submit": "Build",
                        "name": "jobscript.py",
                        "json": json.dumps(
                    {"parameter": {"name": "jobscript.py", "file": "file0"}}),
            },
                files={"file0": ("file0", inputfile)})
    except session.Errors:
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
        abort_submit(400, "%r is not a valid archive name" %(filename))
    if normalize_name(filename).startswith(normalize_name(name)):
        return
    abort_submit(400, "filename %r does not match project name %r"
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

