from __future__ import unicode_literals

import collections
import os
import py
import re
from time import time
from devpi_common.types import ensure_unicode
from devpi_common.url import URL
from devpi_common.metadata import get_pyversion_filetype
import devpi_server
from pyramid.compat import urlparse
from pyramid.interfaces import IAuthenticationPolicy
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

from .filestore import BadGateway
from .model import InvalidIndex, InvalidIndexconfig, InvalidUser
from .model import get_ixconfigattrs
from .readonly import get_mutable_deepcopy
from .log import thread_push_log, thread_pop_log, threadlog

from .auth import Auth

server_version = devpi_server.__version__


H_MASTER_UUID = str("X-DEVPI-MASTER-UUID")


API_VERSION = "2"

# we use str() here so that python2.6 gets bytes, python3.3 gets string
# so that wsgiref's parsing does not choke

meta_headers = {str("X-DEVPI-API-VERSION"): str(API_VERSION),
                str("X-DEVPI-SERVER-VERSION"): server_version}


INSTALLER_USER_AGENT = r"([^ ]* )*(distribute|setuptools|pip|pex)/.*"


def abort(request, code, body):
    # if no Accept header is set, then force */*, otherwise the exception
    # will be returned as text/plain, which causes easy_install/setuptools
    # to fail improperly
    request.headers.setdefault("Accept", "*/*")
    if "application/json" in request.headers.get("Accept", ""):
        apireturn(code, body)
    threadlog.error("while handling %s:\n%s" % (request.url, body))
    raise exception_response(code, explanation=body, headers=meta_headers)


def abort_submit(request, code, msg, level="error"):
    # we construct our own type because we need to set the title
    # so that setup.py upload/register use it to explain the failure
    error = type(
        str('HTTPError'), (HTTPException,), dict(
            code=code, title=msg))
    if level == "info":
        threadlog.info("while handling %s:\n%s" % (request.url, msg))
    elif level == "warn":
        threadlog.warn("while handling %s:\n%s" % (request.url, msg))
    else:
        threadlog.error("while handling %s:\n%s" % (request.url, msg))
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


class ContentTypePredicate(object):
    def __init__(self, val, config):
        self.val = val

    def text(self):
        return 'content type = %s' % self.val
    phash = text

    def __call__(self, context, request):
        return request.content_type == self.val


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
        set_header_devpi_serial(response, tx)
        return response
    return request_tx_handler


def set_header_devpi_serial(response, tx):
    if isinstance(response._app_iter, collections.Iterator):
        return
    if tx.commit_serial is not None:
        serial = tx.commit_serial
    else:
        serial = tx.at_serial
    response.headers[str("X-DEVPI-SERIAL")] = str(serial)


def is_mutating_http_method(method):
    return method in ("PUT", "POST", "PATCH", "DELETE", "PUSH")

class StatusView:
    def __init__(self, request):
        self.request = request
        self.xom = request.registry["xom"]

    def _status(self):
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
            "last-commit-timestamp": self.xom.keyfs.get_last_commit_timestamp(),
            "event-serial": self.xom.keyfs.notifier.read_event_serial(),
            "event-serial-timestamp":
                self.xom.keyfs.notifier.get_event_serial_timestamp(),
            "event-serial-in-sync-at":
                self.xom.keyfs.notifier.event_serial_in_sync_at,
        }
        master_url = config.args.master_url
        if master_url:
            from .replica import ReplicationErrors
            status["role"] = "REPLICA"
            status["master-url"] = master_url
            status["master-uuid"] = config.nodeinfo.get("master-uuid")
            status["master-serial"] = self.xom.replica_thread.get_master_serial()
            status["master-serial-timestamp"] = self.xom.replica_thread.get_master_serial_timestamp()
            status["replica-started-at"] = self.xom.replica_thread.started_at
            status["master-contacted-at"] = self.xom.replica_thread.master_contacted_at
            status["update-from-master-at"] = self.xom.replica_thread.update_from_master_at
            status["replica-in-sync-at"] = self.xom.replica_thread.replica_in_sync_at
            replication_errors = ReplicationErrors(self.xom.config.serverdir)
            status["replication-errors"] = replication_errors.errors
        else:
            status["role"] = "MASTER"
        status["polling_replicas"] = self.xom.polling_replicas
        return status

    @view_config(route_name="/+status", accept="application/json")
    def status(self):
        apireturn(200, type="status", result=self._status())


def devpiweb_get_status_info(request):
    msgs = []
    status = StatusView(request)._status()
    now = time()
    if status["role"] == "REPLICA":
        master_serial = status["master-serial"]
        if master_serial is not None and master_serial > status["serial"]:
            if status["replica-in-sync-at"] is None or (now - status["replica-in-sync-at"]) > 300:
                msgs.append(dict(status="fatal", msg="Replica is behind master for more than 5 minutes"))
            elif (now - status["replica-in-sync-at"]) > 60:
                msgs.append(dict(status="warn", msg="Replica is behind master for more than 1 minute"))
        else:
            if len(status["replication-errors"]):
                msgs.append(dict(status="fatal", msg="Unhandled replication errors"))
        if status["replica-started-at"] is not None:
            last_update = status["update-from-master-at"]
            if last_update is None:
                if (now - status["replica-started-at"]) > 300:
                    msgs.append(dict(status="fatal", msg="No contact to master for more than 5 minutes"))
                elif (now - status["replica-started-at"]) > 60:
                    msgs.append(dict(status="warn", msg="No contact to master for more than 1 minute"))
            elif (now - last_update) > 300:
                msgs.append(dict(status="fatal", msg="No update from master for more than 5 minutes"))
            elif (now - last_update) > 60:
                msgs.append(dict(status="warn", msg="No update from master for more than 1 minute"))
    if status["serial"] > status["event-serial"]:
        if status["event-serial-in-sync-at"] is None:
            sync_at = None
        else:
            sync_at = now - status["event-serial-in-sync-at"]
        if status["event-serial-timestamp"] is None:
            last_processed = None
        else:
            last_processed = now - status["event-serial-timestamp"]
        if sync_at is None and last_processed is None and (now - status["last-commit-timestamp"]) <= 300:
            pass
        elif sync_at is None and last_processed is None and (now - status["last-commit-timestamp"]) > 300:
            msgs.append(dict(status="fatal", msg="The event processing doesn't seem to start"))
        elif sync_at is None or (sync_at > 21600):
            msgs.append(dict(status="fatal", msg="The event processing hasn't been in sync for more than 6 hours"))
        elif sync_at > 3600:
            msgs.append(dict(status="warn", msg="The event processing hasn't been in sync for more than 1 hour"))
        if sync_at is not None and (last_processed is None or (last_processed > 1800)):
            msgs.append(dict(status="fatal", msg="No changes processed by plugins for more than 30 minutes"))
        elif sync_at is not None and (last_processed > 300):
            msgs.append(dict(status="warn", msg="No changes processed by plugins for more than 5 minutes"))
    return msgs


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

    @view_config(route_name="/{user}/{index}/+simple/{project}")
    def simple_list_project(self):
        request = self.request
        abort_if_invalid_project(request, request.matchdict["project"])
        project = self.context.project
        # we only serve absolute links so we don't care about the route's slash
        stage = self.context.stage
        requested_by_pip = re.match(INSTALLER_USER_AGENT,
            request.user_agent or "")
        try:
            result = stage.get_simplelinks(project, sorted_links=not requested_by_pip)
        except stage.UpstreamError as e:
            threadlog.error(e.msg)
            abort(request, 502, e.msg)

        if not result:
            self.request.context.verified_project  # access will trigger 404 if not found

        if requested_by_pip:
            # we don't need the extra stuff on the simple page for pip
            embed_form = False
            blocked_index = None
        else:
            # only mere humans need to know and do more
            whitelist_info = stage.get_mirror_whitelist_info(project)
            embed_form = whitelist_info['has_mirror_base']
            blocked_index = whitelist_info['blocked_by_mirror_whitelist']
        response = Response(body=b"".join(self._simple_list_project(
            stage, project, result, embed_form, blocked_index)))
        if stage.ixconfig['type'] == 'mirror':
            serial = stage.key_projsimplelinks(project).get().get("serial")
            if serial > 0:
                response.headers[str("X-PYPI-LAST-SERIAL")] = str(serial)
        return response

    def _simple_list_project(self, stage, project, result, embed_form, blocked_index):
        response = self.request.response
        response.content_type = "text/html ; charset=utf-8"

        title = "%s: links for %s" % (stage.name, project)
        yield ("<html><head><title>%s</title></head><body><h1>%s</h1>\n" %
               (title, title)).encode("utf-8")

        if embed_form:
            yield self._index_refresh_form(stage, project).encode("utf-8")

        if blocked_index:
            yield ("<p><strong>INFO:</strong> Because this project isn't in "
                   "the <code>mirror_whitelist</code>, no releases from "
                   "<strong>%s</strong> are included.</p>"
                   % blocked_index).encode('utf-8')

        url = URL(self.request.path_info)
        for key, href in result:
            yield ('%s <a href="%s">%s</a><br/>\n' %
                   ("/".join(href.split("/", 2)[:2]),
                    url.relpath("/" + href),
                    key)).encode("utf-8")

        yield "</body></html>".encode("utf-8")

    def _index_refresh_form(self, stage, project):
        url = self.request.route_url(
            "/{user}/{index}/+simple/{project}/refresh",
            user=self.context.username, index=self.context.index,
            project=project)
        title = "Refresh" if stage.ixconfig["type"] == "mirror" else "Refresh PyPI links"
        submit = '<input name="refresh" type="submit" value="%s"/>' % title
        return '<form action="%s" method="post">%s</form>' % (url, submit)

    @view_config(route_name="/{user}/{index}/+simple/")
    def simple_list_all(self):
        self.log.info("starting +simple")
        stage = self.context.stage
        try:
            stage_results = list(stage.op_sro("list_projects_perstage"))
        except stage.UpstreamError as e:
            threadlog.error(e.msg)
            abort(self.request, 502, e.msg)
        # at this point we are sure we can produce the data without
        # depending on remote networks
        return Response(body=b"".join(self._simple_list_all(stage, stage_results)))

    def _simple_list_all(self, stage, stage_results):
        response = self.request.response
        response.content_type = "text/html ; charset=utf-8"
        title =  "%s: simple list (including inherited indices)" %(
                 stage.name)
        yield ("<html><head><title>%s</title></head><body><h1>%s</h1>" %(
              title, title)).encode("utf-8")
        all_names = set()
        for stage, names in stage_results:
            h2 = stage.name
            bases = getattr(stage, "ixconfig", {}).get("bases")
            if bases:
                h2 += " (bases: %s)" % ",".join(bases)
            yield ("<h2>" + h2 + "</h2>").encode("utf-8")
            for name in sorted(names):
                if name not in all_names:
                    anchor = '<a href="%s">%s</a><br/>\n' % (name, name)
                    yield anchor.encode("utf-8")
                    all_names.add(name)
        yield "</body>".encode("utf-8")

    @view_config(
        route_name="/{user}/{index}/+simple/{project}/refresh", request_method="POST")
    def simple_refresh(self):
        context = self.context
        for stage in context.stage.sro():
            if stage.ixconfig["type"] != "mirror":
                continue
            stage.clear_simplelinks_cache(context.project)
            stage.get_simplelinks_perstage(context.project)
        redirect(self.request.route_url(
            "/{user}/{index}/+simple/{project}",
            user=context.username, index=context.index, project=context.project))

    @view_config(
        route_name="/{user}/{index}", request_method="PUT")
    def index_create(self):
        username = self.context.username
        user = self.model.get_user(username)
        if user is None:
            # If the currently authenticated user tries to create an index,
            # we create a user object automatically. The user object may
            # not exist if the user was authenticated by a plugin.
            if self.request.authenticated_userid == username:
                registry = self.request.registry
                auth_policy = registry.queryUtility(IAuthenticationPolicy)
                # we verify the credentials explicitly here, because the
                # provided token may belong to a deleted user
                if auth_policy.verify_credentials(self.request):
                    try:
                        user = self.model.create_user(username, password=None)
                    except InvalidUser as e:
                        apireturn(400, "%s" % e)
        stage = self.context.user.getstage(self.context.index)
        if stage is not None:
            apireturn(409, "index %r exists" % stage.name)
        if not self.request.has_permission("index_create"):
            apireturn(403, "no permission to create index %s/%s" % (
                self.context.username, self.context.index))
        kvdict = getkvdict_index(self.xom.config.hook, getjson(self.request))
        try:
            stage = self.context.user.create_stage(self.context.index, **kvdict)
            ixconfig = stage.ixconfig
        except InvalidIndex as e:
            apireturn(400, "%s" % e)
        except InvalidIndexconfig as e:
            apireturn(400, message=", ".join(e.messages))
        apireturn(200, type="indexconfig", result=ixconfig)

    @view_config(
        route_name="/{user}/{index}", request_method="PATCH",
        permission="index_modify")
    def index_modify(self):
        stage = self.context.stage
        kvdict = getkvdict_index(self.xom.config.hook, getjson(self.request))
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
            except BadGateway as e:
                return apireturn(502, e.args[0])
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
            if should_fetch_remote_file(link.entry, self.request.headers):
                for part in iter_fetch_remote_file(self.xom, link.entry):
                    pass
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
            abort_submit(request, 404, "cannot submit to pypi mirror")
        stage = self.context.stage
        if not request.has_permission("pypi_submit"):
            # if there is no authenticated user, then issue a basic auth challenge
            if not request.authenticated_userid:
                response = HTTPUnauthorized()
                response.headers.update(forget(request))
                return response
            abort_submit(request, 403, "no permission to submit")
        try:
            action = request.POST[":action"]
        except KeyError:
            abort_submit(request, 400, ":action field not found")
        if action == "submit":
            self._set_versiondata_form(stage, request.POST)
            return Response("")
        elif action in ("doc_upload", "file_upload"):
            try:
                content = request.POST["content"]
            except KeyError:
                abort_submit(request, 400, "content file field not found")
            name = ensure_unicode(request.POST.get("name"))
            # version may be empty on plain doczip uploads
            version = ensure_unicode(request.POST.get("version") or "")
            project = normalize_name(name)
            if not stage.has_project(name):
                abort_submit(
                    request, 400,
                    "no project named %r was ever registered" % (name))

            if action == "file_upload":
                self.log.debug("metadata in form: %s",
                               list(request.POST.items()))

                # we only check for release files if version is
                # contained in the filename because for doczip files
                # we construct the filename ourselves anyway.
                if version and version not in content.filename:
                    abort_submit(
                        request, 400,
                        "filename %r does not contain version %r" % (
                            content.filename, version))

                abort_if_invalid_filename(request, name, content.filename)
                metadata = stage.get_versiondata_perstage(project, version)
                if not metadata:
                    self._set_versiondata_form(stage, request.POST)
                    metadata = stage.get_versiondata(project, version)
                    if not metadata:
                        abort_submit(
                            request, 400, "could not process form metadata")
                file_content = content.file.read()
                try:
                    link = stage.store_releasefile(
                        project, version,
                        content.filename, file_content)
                except stage.NonVolatile as e:
                    if e.link.matches_checksum(file_content):
                        abort_submit(
                            request, 200,
                            "Upload of identical file to non volatile index.",
                            level="info")
                    abort_submit(
                        request, 409,
                        "%s already exists in non-volatile index" % (
                            content.filename,))
                link.add_log(
                    'upload', request.authenticated_userid, dst=stage.name)
                try:
                    self.xom.config.hook.devpiserver_on_upload_sync(
                        log=request.log, application_url=request.application_url,
                        stage=stage, project=project, version=version)
                except Exception as e:
                    abort_submit(
                        request, 200,
                        "OK, but a trigger plugin failed: %s" % e, level="warn")
            else:
                doczip = content.file.read()
                try:
                    link = stage.store_doczip(project, version, doczip)
                except stage.MissesRegistration:
                    abort_submit(
                        request, 400,
                        "%s-%s is not registered" % (name, version))
                except stage.NonVolatile as e:
                    if e.link.matches_checksum(doczip):
                        abort_submit(
                            request, 200,
                            "Upload of identical file to non volatile index.",
                            level="info")
                    abort_submit(
                        request, 409,
                        "%s already exists in non-volatile index" % (
                            content.filename,))
                link.add_log(
                    'upload', request.authenticated_userid, dst=stage.name)
        else:
            abort_submit(request, 400, "action %r not supported" % action)
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
            abort_submit(self.request, 400, "invalid metadata: %s" % (e,))
        self.log.info("%s: got submit release info %r",
                 stage.name, metadata["name"])

    #
    #  per-project and version data
    #

    @view_config(route_name="simple_redirect")
    def simple_redirect(self):
        stage, name = self.context.stage, self.context.project
        redirect("/%s/+simple/%s" % (stage.name, name))

    @view_config(route_name="/{user}/{index}/{project}",
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
        route_name="/{user}/{index}/{project}", request_method="DELETE",
        permission="del_project")
    def del_project(self):
        stage = self.context.stage
        if stage.ixconfig["type"] == "mirror":
            abort(self.request, 405, "cannot delete on mirror index")
        project = self.context.project
        if not stage.ixconfig["volatile"]:
            apireturn(403, "project %r is on non-volatile index %s" %(
                      project, stage.name))
        try:
            stage.del_project(project)
        except KeyError:
            apireturn(404, "project not found")
        apireturn(200, "project {project} deleted from stage {sname}".format(
                  project=project, sname=stage.name))

    @view_config(route_name="/{user}/{index}/{project}/{version}", accept="application/json", request_method="GET")
    def version_get(self):
        verdata = self.context.get_versiondata(perstage=False)
        view_verdata = self._make_view_verdata(verdata)
        apireturn(200, type="versiondata", result=view_verdata)

    def _make_view_verdata(self, verdata):
        view_verdata = get_mutable_deepcopy(verdata)
        elinks = view_verdata.pop("+elinks", None)
        if elinks is not None:
            view_verdata["+links"] = links = []
            for linkdict in elinks:
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

    @view_config(route_name="/{user}/{index}/{project}/{version}",
                 permission="del_verdata",
                 request_method="DELETE")
    def del_versiondata(self):
        stage = self.context.stage
        name, version = self.context.project, self.context.version
        if stage.ixconfig["type"] == "mirror":
            abort(self.request, 405, "cannot delete on mirror index")
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
            entry_data = get_mutable_deepcopy(entry.meta)
            apireturn(200, type="releasefilemeta", result=entry_data)
        if not entry or not entry.meta:
            if entry is None:
                abort(request, 404, "no such file")
            else:
                abort(request, 410, "file existed, deleted in later serial")

        try:
            if should_fetch_remote_file(entry, request.headers):
                app_iter = iter_fetch_remote_file(self.xom, entry)
                headers = next(app_iter)
                return Response(app_iter=app_iter, headers=headers)
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
        result['projects'] = sorted(stage.list_projects_perstage())
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
        ignored_keys = set(('indexes', 'username'))
        allowed_keys = set((
            "email", "password", "title", "description", "custom_data"))
        result = getjson(request, allowed_keys=allowed_keys.union(ignored_keys))
        kvdict = dict()
        for key in allowed_keys:
            if key not in result:
                continue
            kvdict[key] = result[key]
        user = self.context.user
        password = kvdict.get("password")
        user.modify(**kvdict)
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


def iter_fetch_remote_file(xom, entry):
    filestore = xom.filestore
    keyfs = xom.keyfs
    if not xom.is_replica():
        keyfs.restart_as_write_transaction()
        entry = filestore.get_file_entry(entry.relpath, readonly=False)
        for part in entry.iter_cache_remote_file():
            yield part
    else:
        for part in entry.iter_remote_file_replica():
            yield part


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


def abort_if_invalid_filename(request, name, filename):
    if not is_valid_archive_name(filename):
        abort_submit(request, 400, "%r is not a valid archive name" %(filename))
    if normalize_name(filename).startswith(normalize_name(name)):
        return
    abort_submit(request, 400, "filename %r does not match project name %r"
                      %(filename, name))

def abort_if_invalid_project(request, project):
    try:
        if isinstance(project, bytes):
            project.decode("ascii")
        else:
            project.encode("ascii")
    except (UnicodeEncodeError, UnicodeDecodeError):
        abort(request, 400, "unicode project names not allowed")


def getkvdict_index(hook, req):
    kvdict = {}
    ixconfigattrs = get_ixconfigattrs(hook, req.get("type", "stage"))
    for key in ixconfigattrs:
        if key in req:
            kvdict[key] = req[key]
    return kvdict

def get_pure_metadata(somedict):
    metadata = {}
    for n, v in somedict.items():
        if n[0] != "+":
            metadata[n] = v
    return metadata

