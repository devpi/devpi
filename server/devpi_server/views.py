from __future__ import unicode_literals

import os
import py
import re
import traceback
from time import time
try:
    from collections.abc import Iterator
except ImportError:
    from collections import Iterator
from devpi_common.types import ensure_unicode
from devpi_common.url import URL
from devpi_common.metadata import get_pyversion_filetype
import devpi_server
from html import escape
from io import BytesIO
from lazy import lazy
from pluggy import HookimplMarker
from pyramid.authentication import b64encode
from pyramid.interfaces import IRequestExtensions
from pyramid.interfaces import IRootFactory
from pyramid.interfaces import IRoutesMapper
from pyramid.httpexceptions import HTTPException, HTTPFound, HTTPSuccessful
from pyramid.httpexceptions import HTTPForbidden
from pyramid.httpexceptions import HTTPOk
from pyramid.httpexceptions import HTTPUnauthorized
from pyramid.httpexceptions import exception_response
from pyramid.request import Request
from pyramid.request import apply_request_extensions
from pyramid.response import Response
from pyramid.security import forget
from pyramid.threadlocal import RequestContext
from pyramid.traversal import DefaultRootFactory
from pyramid.view import exception_view_config
from pyramid.view import view_config
from urllib.parse import urlparse
import itertools
import json
from devpi_common.request import new_requests_session
from devpi_common.validation import normalize_name, is_valid_archive_name

from .config import hookimpl
from .filestore import BadGateway
from .model import InvalidIndex, InvalidIndexconfig, InvalidUser, InvalidUserconfig
from .model import ReadonlyIndex
from .model import RemoveValue
from .readonly import get_mutable_deepcopy
from .log import thread_push_log, thread_pop_log, threadlog

from .auth import Auth

devpiweb_hookimpl = HookimplMarker("devpiweb")
server_version = devpi_server.__version__


H_MASTER_UUID = str("X-DEVPI-MASTER-UUID")


API_VERSION = "2"

# we use str() here so that Python 2 gets bytes, Python 3 gets string
# so that wsgiref's parsing does not choke

meta_headers = {str("X-DEVPI-API-VERSION"): str(API_VERSION),
                str("X-DEVPI-SERVER-VERSION"): server_version}


INSTALLER_USER_AGENT = r"([^ ]* )*(distribute|setuptools|pip|pex)/.*"
INSTALLER_USER_AGENT_REGEXP = re.compile(INSTALLER_USER_AGENT)


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


def apireturn(code, message=None, result=None, type=None):
    d = dict()
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
        outside_url = environ.get('HTTP_X_OUTSIDE_URL')
        if not outside_url:
            outside_url = self.xom.config.args.outside_url
        if outside_url:
            # XXX memoize it for later access from replica thread
            # self.xom.current_outside_url = outside_url
            outside_url = urlparse(outside_url)
            environ['wsgi.url_scheme'] = outside_url.scheme
            environ['HTTP_HOST'] = outside_url.netloc
            if outside_url.path:
                environ['SCRIPT_NAME'] = outside_url.path
        return self.app(environ, start_response)


def route_url(self, *args, **kw):
    url = super(self.__class__, self).route_url(*args, **kw)
    # Unquote plus signs in path segment. The settings in pyramid for
    # the urllib quoting function are a bit too much on the safe side
    url = urlparse(url)
    url = url._replace(path=url.path.replace('%2B', '+'))
    return url.geturl()


def tween_request_logging(handler, registry):
    req_count = itertools.count()

    nodeinfo = registry["xom"].config.nodeinfo

    def request_log_handler(request):
        tag = "[req%s]" %(next(req_count))
        log = thread_push_log(tag)
        try:
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
                      response.status,
                      duration,
                      serial,
                      rheaders.get("content-length"),
                      rheaders.get("content-type"))
        finally:
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
        write = is_mutating_http_method(request.method) and not is_replica
        with keyfs.transaction(write=write) as tx:
            threadlog.debug("in-transaction %s", tx.at_serial)
            response = handler(request)
        set_header_devpi_serial(response, tx)
        return response
    return request_tx_handler


def set_header_devpi_serial(response, tx):
    if isinstance(response._app_iter, Iterator):
        return
    if tx.commit_serial is not None:
        serial = tx.commit_serial
    else:
        serial = tx.at_serial
    response.headers[str("X-DEVPI-SERIAL")] = str(serial)


def is_mutating_http_method(method):
    return method in ("PUT", "POST", "PATCH", "DELETE", "PUSH")


def get_actions(json):
    result = []
    for item in json:
        key, sep, value = item.partition('=')
        if key.endswith('+'):
            op = 'add'
            key = key[:-1]
        elif key.endswith('-'):
            if value == '':
                op = 'drop'
            else:
                op = 'del'
            key = key[:-1]
        else:
            op = 'set'
        result.append((op, key, value))
    return result


@exception_view_config(ReadonlyIndex)
def readonly_index_view(exc, request):
    response = Response("%s" % exc)
    response.status = "405 %s" % exc
    return response


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
            "metrics": [],
        }
        seen = set()
        for results in config.hook.devpiserver_metrics(request=self.request):
            for metric in results:
                name = metric[0]
                if name in seen:
                    raise RuntimeError(
                        "A plugin returned a metric with the name '%s' which "
                        "is already used." % name)
                seen.add(name)
                status["metrics"].append(metric)
        if self.xom.is_replica():
            status["role"] = "REPLICA"
            status["master-url"] = config.master_url.url
            status["master-uuid"] = config.get_master_uuid()
            status["master-serial"] = self.xom.replica_thread.get_master_serial()
            status["master-serial-timestamp"] = self.xom.replica_thread.get_master_serial_timestamp()
            status["replica-started-at"] = self.xom.replica_thread.started_at
            status["master-contacted-at"] = self.xom.replica_thread.master_contacted_at
            status["update-from-master-at"] = self.xom.replica_thread.update_from_master_at
            status["replica-in-sync-at"] = self.xom.replica_thread.replica_in_sync_at
            replication_errors = self.xom.replica_thread.shared_data.errors
            status["replication-errors"] = replication_errors.errors
        else:
            status["role"] = "MASTER"
        status["polling_replicas"] = self.xom.polling_replicas
        return status

    @view_config(route_name="/+status", accept="application/json")
    def status(self):
        apireturn(200, type="status", result=self._status())


@devpiweb_hookimpl
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


@hookimpl
def devpiserver_authcheck_always_ok(request):
    route = request.matched_route
    if route and route.name.endswith('/+api'):
        return True
    if route and route.name == '/+login':
        return True


@hookimpl
def devpiserver_authcheck_forbidden(request):
    route = request.matched_route
    if not route:
        return
    route_names = (
        '/{user}/{index}/+e/{relpath:.*}',
        '/{user}/{index}/+f/{relpath:.*}')
    if route.name not in route_names:
        return
    if not request.has_permission('pkg_read'):
        return True


class PyPIView:
    def __init__(self, request):
        self.request = request
        self.context = request.context
        xom = request.registry['xom']
        self.xom = xom
        self.model = xom.model
        self.auth = Auth(self.model, xom.config.get_auth_secret())
        self.log = request.log

    def get_auth_status(self):
        identity = self.request.identity
        if identity is None:
            return ["noauth", "", []]
        return ["ok", identity.username, identity.groups]

    #
    # supplying basic API locations for all services
    #

    @view_config(route_name="/+api")
    @view_config(route_name="/{user}/+api")
    @view_config(route_name="/{user}/{index}/+api")
    def apiconfig_index(self):
        request = self.request
        stage = None
        if request.context.index is not None:
            stage = request.context.stage
        api = {
            "login": request.route_url('/+login'),
            "authstatus": self.get_auth_status(),
            "features": self.xom.supported_features,
        }
        if stage is not None:
            api.update({
                "index": request.stage_url(stage),
                "simpleindex": request.simpleindex_url(stage)
            })
            if stage.ixconfig["type"] != "mirror":
                api["pypisubmit"] = request.route_url(
                    "/{user}/{index}/", user=stage.username, index=stage.index)
        apireturn(200, type="apiconfig", result=api)

    def _auth_check_request(self, request):
        hook = self.xom.config.hook
        result = hook.devpiserver_authcheck_always_ok(request=request)
        if result and all(result):
            threadlog.debug(
                "Authcheck always OK for %s (%s)",
                request.url, request.matched_route.name)
            return HTTPOk()
        if hook.devpiserver_authcheck_forbidden(request=request):
            threadlog.debug(
                "Authcheck Forbidden for %s (%s)",
                request.url, request.matched_route.name)
            return HTTPForbidden()
        if not hook.devpiserver_authcheck_unauthorized(request=request):
            threadlog.debug(
                "Authcheck OK for %s (%s)",
                request.url, request.matched_route.name)
            return HTTPOk()
        threadlog.debug(
            "Authcheck Unauthorized for %s (%s)",
            request.url, request.matched_route.name)
        user_agent = request.user_agent or ""
        if 'devpi-client' in user_agent:
            # devpi-client needs to know for proper error messages
            return HTTPForbidden()
        return HTTPUnauthorized()

    @view_config(route_name="/+authcheck")
    def authcheck_view(self):
        request = self.request
        routes_mapper = request.registry.queryUtility(IRoutesMapper)
        root_factory = request.registry.queryUtility(
            IRootFactory, default=DefaultRootFactory)
        request_extensions = request.registry.queryUtility(IRequestExtensions)
        url = request.headers.get('x-original-uri', request.url)
        orig_request = Request.blank(url, headers=request.headers)
        orig_request.log = request.log
        orig_request.registry = request.registry
        if request_extensions:
            apply_request_extensions(
                orig_request, extensions=request_extensions)
        info = routes_mapper(orig_request)
        (orig_request.matchdict, orig_request.matched_route) = (
            info['match'], info['route'])
        root_factory = orig_request.matched_route.factory or root_factory
        orig_request.context = root_factory(orig_request)
        with RequestContext(orig_request):
            return self._auth_check_request(orig_request)

    #
    # attach test results to release files
    #

    @view_config(route_name="/{user}/{index}/+f/{relpath:.*}",
        request_method="POST",
        permission="toxresult_upload")
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

    @property
    def _use_absolute_urls(self):
        if self.xom.config.args.absolute_urls:
            return True
        if 'HTTP_X_DEVPI_ABSOLUTE_URLS' in self.request.environ:
            return True
        return False

    @view_config(route_name="/{user}/{index}/+simple/{project}")
    def simple_list_project_redirect(self):
        """
        PEP 503:
        the repository SHOULD redirect the URLs without a /
        to add a / to the end
        """
        request = self.request
        abort_if_invalid_project(request, request.matchdict["project"])
        requested_by_installer = INSTALLER_USER_AGENT_REGEXP.match(
            request.user_agent or "")
        if requested_by_installer:
            # for performance reasons we return results directly for
            # known installers
            return self.simple_list_project()
        return HTTPFound(location=self.request.route_url(
            "/{user}/{index}/+simple/{project}/",
            user=self.context.username,
            index=self.context.index,
            project=self.context.project))

    @view_config(route_name="/{user}/{index}/+simple/{project}/")
    def simple_list_project(self):
        request = self.request
        abort_if_invalid_project(request, request.matchdict["project"])
        project = self.context.project
        # we only serve absolute links so we don't care about the route's slash
        stage = self.context.stage
        requested_by_installer = INSTALLER_USER_AGENT_REGEXP.match(
            request.user_agent or "")
        try:
            result = stage.get_simplelinks(project, sorted_links=not requested_by_installer)
        except stage.UpstreamError as e:
            threadlog.error(e.msg)
            abort(request, 502, e.msg)

        if not result:
            self.request.context.verified_project  # access will trigger 404 if not found

        if requested_by_installer:
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
        yield ("<!DOCTYPE html><html><head><title>%s</title></head><body><h1>%s</h1>\n" %
               (title, title)).encode("utf-8")

        if embed_form:
            yield self._index_refresh_form(stage, project).encode("utf-8")

        if blocked_index:
            yield ("<p><strong>INFO:</strong> Because this project isn't in "
                   "the <code>mirror_whitelist</code>, no releases from "
                   "<strong>%s</strong> are included.</p>"
                   % blocked_index).encode('utf-8')

        if self._use_absolute_urls:
            # for joinpath we need the root url
            application_url = self.request.application_url
            if not application_url.endswith("/"):
                application_url = application_url + "/"
            url = URL(application_url)

            def make_url(href):
                return url.joinpath(href).url
        else:
            # for relpath we need the path of the current page
            url = URL(self.request.path_info)

            def make_url(href):
                return url.relpath("/" + href)

        for key, href, require_python, yanked in result:
            stage = "/".join(href.split("/", 2)[:2])
            attribs = 'href="%s"' % make_url(href)
            if require_python is not None:
                attribs += ' data-requires-python="%s"' % escape(require_python)
            if yanked:
                attribs += ' data-yanked=""'
            data = dict(stage=stage, attribs=attribs, key=key)
            yield '{stage} <a {attribs}>{key}</a><br/>\n'.format(
                **data).encode('utf-8')

        yield "</body></html>".encode("utf-8")

    def _index_refresh_form(self, stage, project):
        url = self.request.route_url(
            "/{user}/{index}/+simple/{project}/refresh",
            user=self.context.username, index=self.context.index,
            project=project)
        title = "Refresh" if stage.ixconfig["type"] == "mirror" else "Refresh PyPI links"
        submit = '<input name="refresh" type="submit" value="%s"/>' % title
        return '<form action="%s" method="post">%s</form>' % (url, submit)

    @view_config(route_name="/{user}/{index}/+simple")
    def simple_list_all_redirect(self):
        """
        PEP 503:
        the repository SHOULD redirect the URLs without a /
        to add a / to the end
        """
        request = self.request
        requested_by_installer = INSTALLER_USER_AGENT_REGEXP.match(
            request.user_agent or "")
        if requested_by_installer:
            # for performance reasons we return results directly for
            # known installers
            return self.simple_list_project()
        return HTTPFound(location=request.route_url(
            "/{user}/{index}/+simple/",
            user=self.context.username,
            index=self.context.index))

    @view_config(route_name="/{user}/{index}/+simple/")
    def simple_list_all(self):
        self.log.info("starting +simple")
        stage = self.context.stage
        try:
            stage_results = list(stage.list_projects())
        except stage.UpstreamError as e:
            threadlog.error(e.msg)
            abort(self.request, 502, e.msg)
        # at this point we are sure we can produce the data without
        # depending on remote networks
        return Response(body=b"".join(self._simple_list_all(stage, stage_results)))

    def _simple_list_all(self, stage, stage_results):
        response = self.request.response
        response.content_type = "text/html ; charset=utf-8"
        title = "%s: simple list (including inherited indices)" % (stage.name)
        yield ("<!DOCTYPE html><html><head><title>%s</title></head><body><h1>%s</h1>" %(
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
                    anchor = '<a href="%s/">%s</a><br/>\n' % (name, name)
                    yield anchor.encode("utf-8")
                    all_names.add(name)
        yield "</body></html>".encode("utf-8")

    @view_config(
        route_name="/{user}/{index}/+simple/{project}/refresh", request_method="POST")
    def simple_refresh(self):
        context = self.context
        for stage in context.stage.sro():
            if stage.ixconfig["type"] != "mirror":
                continue
            stage.clear_simplelinks_cache(context.project)
            stage.get_simplelinks_perstage(context.project)
        return HTTPFound(location=self.request.route_url(
            "/{user}/{index}/+simple/{project}/",
            user=context.username, index=context.index, project=context.project))

    @view_config(
        route_name="/{user}/{index}", request_method="PUT")
    @view_config(
        route_name="/{user}/{index}/", request_method="PUT")
    def index_create(self):
        username = self.context.username
        user = self.model.get_user(username)
        if user is None:
            # If the currently authenticated user tries to create an index,
            # we create a user object automatically. The user object may
            # not exist if the user was authenticated by a plugin.
            if self.request.authenticated_userid == username:
                if not self.request.has_permission("user_create"):
                    apireturn(403, "no permission to create user %s" % (
                        self.context.username))
                user = self.model.create_user(username, password=None)
                lazy.invalidate(self.context, '_user')
                lazy.invalidate(self.context, 'user')
        stage = self.context.user.getstage(self.context.index)
        if stage is not None:
            apireturn(409, "index %r exists" % stage.name)
        if not self.request.has_permission("index_create"):
            apireturn(403, "no permission to create index %s/%s" % (
                self.context.username, self.context.index))
        json = getjson(self.request)
        try:
            stage = self.context.user.create_stage(self.context.index, **json)
            ixconfig = stage.ixconfig
        except InvalidIndex as e:
            apireturn(400, "%s" % e)
        except InvalidIndexconfig as e:
            apireturn(400, message=", ".join(e.messages))
        try:
            stage.customizer.on_modified(self.request, {})
        except InvalidIndexconfig as e:
            self.request.apifatal(400, message=", ".join(e.messages))
        except HTTPException:
            if not self.request.registry["xom"].keyfs.tx.doomed:
                self.request.apifatal(
                    500,
                    "An HTTPException was raised. In on_modified this is not "
                    "allowed, as it breaks transaction handling. Use "
                    "request.apifatal instead.")
            else:
                raise
        apireturn(200, type="indexconfig", result=ixconfig)

    @view_config(
        route_name="/{user}/{index}", request_method="PATCH",
        permission="index_modify")
    @view_config(
        route_name="/{user}/{index}/", request_method="PATCH",
        permission="index_modify")
    def index_modify(self):
        stage = self.context.stage
        json = getjson(self.request)
        if isinstance(json, list):
            ixconfig = stage.get()
            for op, key, value in get_actions(json):
                if op == 'del':
                    if value not in ixconfig[key]:
                        apireturn(
                            400, "The '%s' setting doesn't have value '%s'" % (key, value))
                    if isinstance(ixconfig[key], tuple):
                        ixconfig[key] = tuple(
                            x for x in ixconfig[key] if x != value)
                    else:
                        ixconfig[key].remove(value)
                elif op == 'add':
                    if isinstance(ixconfig[key], tuple):
                        ixconfig[key] += (value,)
                    else:
                        ixconfig[key].append(value)
                elif op == 'set':
                    ixconfig[key] = value
                elif op == 'drop':
                    ixconfig[key] = RemoveValue
                else:
                    raise ValueError("Unknown operator '%s'." % op)
            json = ixconfig
        if json.get('type') == 'indexconfig' and 'result' in json:
            json = json['result']
        oldconfig = dict(stage.ixconfig)
        try:
            ixconfig = stage.modify(**json)
        except InvalidIndexconfig as e:
            apireturn(400, message=", ".join(e.messages))
        try:
            stage.customizer.on_modified(self.request, oldconfig)
        except InvalidIndexconfig as e:
            self.request.apifatal(400, message=", ".join(e.messages))
        except HTTPException:
            if not self.request.registry["xom"].keyfs.tx.doomed:
                self.request.apifatal(
                    500,
                    "An HTTPException was raised. In on_modified this is not "
                    "allowed, as it breaks transaction handling. Use "
                    "request.apifatal instead.")
            else:
                raise
        apireturn(200, type="indexconfig", result=ixconfig)

    @view_config(
        route_name="/{user}/{index}", request_method="DELETE",
        permission="index_delete")
    @view_config(
        route_name="/{user}/{index}/", request_method="DELETE",
        permission="index_delete")
    def index_delete(self):
        stage = self.context.stage
        if not stage.ixconfig["volatile"]:
            apireturn(403, "index %s non-volatile, cannot delete" %
                           stage.name)
        stage.delete()
        apireturn(201, "index %s deleted" % stage.name)

    @view_config(route_name="/{user}/{index}", request_method=("POST", "PUSH"))
    @view_config(route_name="/{user}/{index}/", request_method=("POST", "PUSH"))
    def pushrelease(self):
        request = self.request
        if request.POST.get(':action'):
            # this is actually a submit
            return self.submit()
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

        if not request.has_permission("pkg_read"):
            abort(request, 403, "package read forbidden")

        metadata = linkstore.metadata

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
            if not request.has_permission("upload", context=target_stage):
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
            metadata["metadata_version"] = "2.1"
            self.log.info("registering %s-%s to %s", name, version, posturl)
            session = new_requests_session(agent=("server", server_version))
            try:
                r = session.post(posturl, data=metadata, auth=pypiauth)
            except Exception as e:
                exc_msg = ''.join(traceback.format_exception_only(e.__class__, e))
                results.append((-1, "exception on register:", exc_msg))
                apireturn(502, result=results, type="actionlog")
            self.log.debug("register returned: %s", r.status_code)
            results.append((r.status_code, "register", name, version))
            ok_codes = (200, 201, 410)
            proceed = (r.status_code in ok_codes)
            if proceed:
                for link in links["releasefile"]:
                    entry = link.entry
                    file_metadata = metadata.copy()
                    file_metadata[":action"] = "file_upload"
                    basename = link.basename
                    pyver, filetype = get_pyversion_filetype(basename)
                    file_metadata["filetype"] = filetype
                    file_metadata["pyversion"] = pyver
                    file_metadata["%s_digest" % link.hash_type] = link.hash_value
                    content = entry.file_get_content()
                    self.log.info("sending %s to %s, metadata %s",
                             basename, posturl, file_metadata)
                    try:
                        r = session.post(
                            posturl, data=file_metadata, auth=pypiauth,
                            files={"content": (basename, content)})
                    except Exception as e:
                        exc_msg = ''.join(traceback.format_exception_only(e.__class__, e))
                        results.append((-1, "exception on release upload:", exc_msg))
                    else:
                        self.log.debug("send finished, status: %s", r.status_code)
                        results.append((r.status_code, "upload", entry.relpath,
                                        r.text))
                if links["doczip"]:
                    doc_metadata = metadata.copy()
                    doc_metadata[":action"] = "doc_upload"
                    doczip = links["doczip"][0].entry.file_get_content()
                    try:
                        r = session.post(
                            posturl, data=doc_metadata, auth=pypiauth,
                            files={"content": (name + ".zip", doczip)})
                    except Exception as e:
                        exc_msg = ''.join(traceback.format_exception_only(e.__class__, e))
                        results.append((-1, "exception on documentation upload:", exc_msg))
                    else:
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
            break  # we only can have one doczip for now

    @view_config(
        route_name="/{user}/{index}/", request_method="POST")
    def submit(self):
        request = self.request
        stage = self.context.stage
        if not hasattr(stage, "store_releasefile"):
            abort_submit(request, 404, "cannot submit to mirror index")
        if not request.has_permission("upload"):
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
            # register always overwrites the metadata
            self._set_versiondata_form(stage, request.POST)
            return Response("")
        elif action in ("doc_upload", "file_upload"):
            try:
                content = request.POST["content"]
            except KeyError:
                abort_submit(request, 400, "content file field not found")
            name = ensure_unicode(request.POST["name"])
            # version may be empty on plain doczip uploads
            version = ensure_unicode(request.POST.get("version") or "")
            project = normalize_name(name)

            if action == "file_upload":
                # we only check for release files if version is
                # contained in the filename because for doczip files
                # we construct the filename ourselves anyway.
                if version and version not in content.filename:
                    abort_submit(
                        request, 400,
                        "filename %r does not contain version %r" % (
                            content.filename, version))

                abort_if_invalid_filename(request, name, content.filename)
                self._update_versiondata_form(stage, request.POST)
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
                try:
                    self.xom.config.hook.devpiserver_on_upload_sync(
                        log=request.log, application_url=request.application_url,
                        stage=stage, project=project, version=version)
                except Exception as e:
                    abort_submit(
                        request, 200,
                        "OK, but a trigger plugin failed: %s" % e, level="warn")
            else:
                if "version" in request.POST:
                    self._update_versiondata_form(stage, request.POST)
                doczip = content.file.read()
                try:
                    link = stage.store_doczip(project, version, doczip)
                except stage.MissesVersion as e:
                    abort_submit(
                        request, 400,
                        "%s" % e)
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

    def _get_versiondata_from_form(self, stage, form, skip_missing=False):
        metadata = {}
        for key in stage.metadata_keys:
            if skip_missing and key not in form:
                continue
            elif key in stage.metadata_list_fields:
                val = [ensure_unicode(item)
                        for item in form.getall(key) if item]
            else:
                val = form.get(key, "")
                if val == "UNKNOWN":
                    val = ""
                assert py.builtin._istext(val), val
            metadata[key] = val
        return metadata

    def _update_versiondata_form(self, stage, form):
        # first we only get metadata without any default values for
        # missing keys
        new_metadata = self._get_versiondata_from_form(
            stage, form, skip_missing=True)
        # now we have the name and version and look for existing metadata
        metadata = stage.get_versiondata_perstage(
            new_metadata["name"], new_metadata["version"], readonly=False)
        if not metadata:
            # there is no existing metadata, so we do a full register
            # with default values for missing metadata
            new_metadata = self._get_versiondata_from_form(stage, form)
        # finally we update and set the metadata
        metadata.update(new_metadata)
        self._set_versiondata_dict(stage, metadata)

    def _set_versiondata_form(self, stage, form):
        metadata = self._get_versiondata_from_form(stage, form)
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

    @view_config(route_name="installer_simple")
    def installer_simple(self):
        """
        When an installer accesses a project without the /+simple part we
        return the links directly to avoid a redirect.
        """
        return self.simple_list_all()

    @view_config(route_name="installer_simple_project")
    def installer_simple_project(self):
        """
        When an installer accesses a project without the /+simple part we
        return the links directly to avoid a redirect.
        """
        return self.simple_list_project()

    @view_config(route_name="/{user}/{index}/{project}",
                 accept="application/json", request_method="GET")
    def project_get(self):
        if not json_preferred(self.request):
            apireturn(415, "unsupported media type %s" %
                      self.request.headers.items())
        perstage = 'ignore_bases' in self.request.GET
        context = self.context
        view_metadata = {}
        versions = context.list_versions(perstage=perstage)
        for version in versions:
            versiondata = context.get_versiondata(
                version=version, perstage=perstage)
            view_metadata[version] = self._make_view_verdata(versiondata)
        apireturn(200, type="projectconfig", result=view_metadata)

    @view_config(
        route_name="/{user}/{index}/{project}", request_method="DELETE",
        permission="del_project")
    def del_project(self):
        stage = self.context.stage
        project = self.context.project
        force = 'force' in self.request.params
        if not stage.ixconfig["volatile"] and not force:
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
        force = 'force' in self.request.params
        if not stage.ixconfig["volatile"] and not force:
            abort(self.request, 403, "cannot delete version on non-volatile index")
        try:
            stage.del_versiondata(name, version)
        except stage.NotFound as e:
            abort(self.request, 404, e.msg)
        apireturn(200, "project %r version %r deleted" % (name, version))

    def _relpath_from_request(self):
        relpath = self.request.path_info.strip("/")
        if "#" in relpath:   # XXX unclear how this happens (did with bottle)
            relpath = relpath.split("#", 1)[0]
        return relpath

    def _pkgserv(self, entry):
        request = self.request
        if entry is None:
            abort(request, 404, "no such file")
        elif not entry.meta:
            abort(request, 410, "file existed, deleted in later serial")

        if json_preferred(request):
            entry_data = get_mutable_deepcopy(entry.meta)
            apireturn(200, type="releasefilemeta", result=entry_data)

        if entry.last_modified is None or not entry.file_exists():
            # The file is in a mirror and either deleted or not yet downloaded.
            # We check whether we should serve the file directly
            # or redirect to the external URL
            stage = self.xom.model.getstage(
                entry.key.params['user'],
                entry.key.params['index'])
            if stage is not None and stage.use_external_url:
                # redirect to external url
                return HTTPFound(location=entry.url)

        if not request.has_permission("pkg_read"):
            abort(request, 403, "package read forbidden")

        try:
            if should_fetch_remote_file(entry, request.headers):
                app_iter = iter_fetch_remote_file(self.xom, entry)
                headers = next(app_iter)
                return Response(app_iter=app_iter, headers=headers)
        except BadGateway as e:
            if e.code == 404:
                return apireturn(404, e.args[0])
            return apireturn(502, e.args[0])

        headers = entry.gethttpheaders()
        if self.request.method == "HEAD":
            return Response(headers=headers)
        else:
            content = entry.file_get_content()
            return Response(body=content, headers=headers)

    @view_config(route_name="/{user}/{index}/+e/{relpath:.*}")
    def mirror_pkgserv(self):
        relpath = self._relpath_from_request()
        # when a release is deleted from a mirror, we update the metadata,
        # hence the key won't exist anymore, but we don't delete the file.
        # We want people to notice that condition by returning a 404, but
        # they can still recover the deleted release from the filesystem
        # manually in case they need it.
        key = self.xom.filestore.get_key_from_relpath(relpath)
        if not key.exists():
            abort(self.request, 404, "no such file")
        entry = self.xom.filestore.get_file_entry_from_key(key)
        return self._pkgserv(entry)

    @view_config(route_name="/{user}/{index}/+f/{relpath:.*}")
    def stage_pkgserv(self):
        relpath = self._relpath_from_request()
        entry = self.xom.filestore.get_file_entry(relpath)
        return self._pkgserv(entry)

    @view_config(route_name="/{user}/{index}/+e/{relpath:.*}",
                 permission="del_entry",
                 request_method="DELETE")
    @view_config(route_name="/{user}/{index}/+f/{relpath:.*}",
                 permission="del_entry",
                 request_method="DELETE")
    def del_pkg(self):
        stage = self.context.stage
        force = 'force' in self.request.params
        if not stage.ixconfig["volatile"] and not force:
            abort(self.request, 403, "cannot delete version on non-volatile index")
        relpath = self.request.path_info.strip("/")
        filestore = self.xom.filestore
        entry = filestore.get_file_entry(relpath)
        if entry is None:
            abort(self.request, 404, "package %r doesn't exist" % relpath)
        try:
            stage.del_entry(entry)
        except stage.NotFound as e:
            abort(self.request, 404, e.msg)
        apireturn(200, "package %r deleted" % relpath)

    @view_config(route_name="/{user}/{index}", accept="application/json", request_method="GET")
    @view_config(route_name="/{user}/{index}/", accept="application/json", request_method="GET")
    def index_get(self):
        stage = self.context.stage
        result = dict(stage.ixconfig)
        # double negation :(
        add_projects = 'no_projects' not in self.request.GET
        if add_projects:
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
        if user is None or password is None:
            abort(request, 400, "Bad request: no user/password specified")
        proxyauth = self.auth.new_proxy_auth(user, password, request=request)
        if proxyauth:
            # set the credentials on the current request
            request.headers['X-Devpi-Auth'] = b64encode(
                "%s:%s" % (user, proxyauth['password']))
            # coherence check of the generated credentials
            if user != request.authenticated_userid:
                apireturn(401, "user %r could not be authenticated" % user)
            # it is possible that a plugin removes the permission to login
            if not request.has_permission('user_login'):
                apireturn(
                    401,
                    "user %r has no permission to login with the "
                    "provided credentials" % user)
            apireturn(
                200, "login successful", type="proxyauth", result=proxyauth)
        apireturn(401, "user %r could not be authenticated" % user)

    @view_config(
        route_name="/{user}", request_method="PATCH",
        permission="user_modify")
    @view_config(
        route_name="/{user}/", request_method="PATCH",
        permission="user_modify")
    def user_patch(self):
        request = self.request
        kvdict = getjson(request)
        user = self.context.user
        password = kvdict.get("password")
        try:
            user.modify(**kvdict)
        except InvalidUserconfig as e:
            apireturn(400, message=", ".join(e.messages))
        if password is not None:
            apireturn(200, "user updated, new proxy auth",
                      type="userpassword",
                      result=self.auth.new_proxy_auth(
                          user.name, password=password, request=request))
        apireturn(200, "user updated")

    @view_config(
        route_name="/{user}", request_method="PUT",
        permission="user_create")
    @view_config(
        route_name="/{user}/", request_method="PUT",
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
            except InvalidUserconfig as e:
                apireturn(400, message=", ".join(e.messages))
            apireturn(201, type="userconfig", result=user.get())
        apireturn(400, "password needs to be set")

    @view_config(
        route_name="/{user}", request_method="DELETE",
        permission="user_delete")
    @view_config(
        route_name="/{user}/", request_method="DELETE",
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
    @view_config(route_name="/{user}/", accept="application/json", request_method="GET")
    def user_get(self):
        if self.context.user is None:
            apireturn(404, "user %r does not exist" % self.context.username)
        userconfig = self.context.user.get()
        apireturn(200, type="userconfig", result=userconfig)

    @view_config(route_name="/", accept="application/json", request_method="GET")
    def user_list(self):
        d = {}
        for user in self.model.get_userlist():
            d[user.name] = user.get()
        apireturn(200, type="list:userconfig", result=d)


def should_fetch_remote_file(entry, headers):
    should_fetch = not entry.file_exists()
    return should_fetch


def _headers_from_response(r):
    content_type = r.headers.get('content-type')
    if not content_type:
        content_type = "application/octet-stream"
    if isinstance(content_type, tuple):
        content_type = content_type[0]
    headers = {
        str("X-Accel-Buffering"): str("no"),  # disable buffering in nginx
        "content-type": content_type}
    if "last-modified" in r.headers:
        headers[str("last-modified")] = r.headers["last-modified"]
    if "content-length" in r.headers:
        headers[str("content-length")] = str(r.headers["content-length"])
    return headers


def iter_cache_remote_file(xom, entry):
    # we get and cache the file and some http headers from remote
    r = xom.httpget(entry.url, allow_redirects=True)
    if r.status_code != 200:
        msg = "error %s getting %s" % (r.status_code, entry.url)
        threadlog.error(msg)
        raise BadGateway(msg, code=r.status_code, url=entry.url)
    threadlog.info("reading remote: %s, target %s", r.url, entry.relpath)
    content_size = r.headers.get("content-length")
    err = None

    yield _headers_from_response(r)

    content = BytesIO()
    while 1:
        data = r.raw.read(10240)
        if not data:
            break
        content.write(data)
        yield data

    content = content.getvalue()

    filesize = len(content)
    if content_size and int(content_size) != filesize:
        err = ValueError(
            "%s: got %s bytes of %r from remote, expected %s" % (
                entry.relpath, filesize, r.url, content_size))
    if not err:
        err = entry.check_checksum(content)

    if err is not None:
        threadlog.error(str(err))
        raise err

    try:
        # when pushing from a mirror to an index, we are still in a
        # transaction
        tx = entry.tx
    except AttributeError:
        # when streaming we won't be in a transaction anymore, so we need
        # to open a new one below
        tx = None

    def set_content():
        entry.file_set_content(content, r.headers.get("last-modified", None))
        if entry.project:
            stage = xom.model.getstage(
                entry.key.params['user'],
                entry.key.params['index'])
            # for mirror indexes this makes sure the project is in the database
            # as soon as a file was fetched
            stage.add_project_name(entry.project)

    if not entry.has_existing_metadata():
        if tx is not None:
            set_content()
        else:
            with xom.keyfs.transaction(write=True):
                set_content()
    else:
        # the file was downloaded before but locally removed, so put
        # it back in place without creating a new serial
        # we need a direct write connection to use the io_file_* methods
        if tx is not None:
            tx.conn.io_file_set(entry._storepath, content)
            threadlog.debug(
                "put missing file back into place: %s", entry._storepath)
        else:
            with xom.keyfs._storage.get_connection(write=True) as conn:
                conn.io_file_set(entry._storepath, content)
                threadlog.debug(
                    "put missing file back into place: %s", entry._storepath)
                conn.commit_files_without_increasing_serial()


def iter_remote_file_replica(xom, entry):
    replication_errors = xom.replica_thread.shared_data.errors
    # construct master URL with param
    url = xom.config.master_url.joinpath(entry.relpath).url
    if not entry.url:
        threadlog.warn("missing private file: %s" % entry.relpath)
    else:
        threadlog.info("replica doesn't have file: %s", entry.relpath)
    (uuid, master_uuid) = make_uuid_headers(xom.config.nodeinfo)
    rt = xom.replica_thread
    token = rt.auth_serializer.dumps(uuid)
    r = xom.httpget(
        url, allow_redirects=True,
        extra_headers={
            rt.H_REPLICA_FILEREPL: str("YES"),
            rt.H_REPLICA_UUID: uuid,
            str('Authorization'): 'Bearer %s' % token})
    if r.status_code != 200:
        msg = "%s: received %s from master" % (url, r.status_code)
        if not entry.url:
            threadlog.error(msg)
            raise BadGateway(msg)
        # try to get from original location
        r = xom.httpget(entry.url, allow_redirects=True)
        if r.status_code != 200:
            msg = "%s\n%s: received %s" % (msg, entry.url, r.status_code)
            threadlog.error(msg)
            raise BadGateway(msg)

    yield _headers_from_response(r)

    content = BytesIO()
    while 1:
        data = r.raw.read(10240)
        if not data:
            break
        content.write(data)
        yield data

    content = content.getvalue()

    err = entry.check_checksum(content)
    if err:
        # the file we got is different, so we fail
        raise BadGateway(str(err))

    try:
        # there is no code path that still has a transaction at this point,
        # but we handle that case just to be safe
        tx = entry.tx
    except AttributeError:
        # when streaming we won't be in a transaction anymore, so we need
        # to open a new one below
        tx = None
    if tx is not None and tx.write:
        entry.tx.conn.io_file_set(entry._storepath, content)
    else:
        # we need a direct write connection to use the io_file_* methods
        with xom.keyfs._storage.get_connection(write=True) as conn:
            conn.io_file_set(entry._storepath, content)
            threadlog.debug(
                "put missing file back into place: %s", entry._storepath)
            conn.commit_files_without_increasing_serial()
    # in case there were errors before, we can now remove them
    replication_errors.remove(entry)


def iter_fetch_remote_file(xom, entry):
    filestore = xom.filestore
    keyfs = xom.keyfs
    if not xom.is_replica():
        if not keyfs.tx.write:
            keyfs.restart_as_write_transaction()
        entry = filestore.get_file_entry(entry.relpath, readonly=False)
        for part in iter_cache_remote_file(xom, entry):
            yield part
    else:
        for part in iter_remote_file_replica(xom, entry):
            yield part


def url_for_entrypath(request, entrypath):
    parts = entrypath.split("/")
    user, index = parts[:2]
    assert parts[2] in ("+f", "+e")
    route_name = "/{user}/{index}/%s/{relpath:.*}" % parts[2]
    relpath = "/".join(parts[3:])
    return request.route_url(
        route_name, user=user, index=index, relpath=relpath)


def getjson(request):
    try:
        d = request.json_body
    except ValueError:
        abort(request, 400, "Bad request: could not decode json")
    return d


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
