from __future__ import annotations

import contextlib
import os
import re
import warnings
from time import time
from collections import defaultdict
from devpi_common.types import ensure_unicode
from devpi_common.url import URL
from devpi_common.metadata import get_pyversion_filetype
import devpi_server
from html import escape
from http import HTTPStatus
from lazy import lazy
from operator import attrgetter
from pluggy import HookimplMarker
from pyramid.authentication import b64encode
from pyramid.interfaces import IRequestExtensions
from pyramid.interfaces import IRootFactory
from pyramid.interfaces import IRoutesMapper
from pyramid.httpexceptions import HTTPException, HTTPFound, HTTPSuccessful
from pyramid.httpexceptions import HTTPForbidden
from pyramid.httpexceptions import HTTPInternalServerError
from pyramid.httpexceptions import HTTPOk
from pyramid.httpexceptions import HTTPUnauthorized
from pyramid.httpexceptions import exception_response
from pyramid.request import Request
from pyramid.request import apply_request_extensions
from pyramid.response import FileIter
from pyramid.response import Response
from pyramid.security import forget
from pyramid.threadlocal import RequestContext
from pyramid.traversal import DefaultRootFactory
from pyramid.view import exception_view_config
from pyramid.view import view_config
from urllib.parse import urlparse
import itertools
import json
from devpi_common.validation import normalize_name, is_valid_archive_name

from .config import NodeInfo
from .config import hookimpl
from .exceptions import lazy_format_exception_only
from .filestore import BadGateway
from .filestore import RunningHashes
from .filestore import get_hashes
from .filestore import get_seekable_content_or_file
from .fileutil import buffered_iterator
from .keyfs import KeyfsTimeoutError
from .model import InvalidIndex, InvalidIndexconfig, InvalidUser, InvalidUserconfig
from .model import ReadonlyIndex
from .model import RemoveValue
from .readonly import get_mutable_deepcopy
from .log import thread_push_log, thread_pop_log, threadlog

from .auth import Auth
import attrs

devpiweb_hookimpl = HookimplMarker("devpiweb")
server_version = devpi_server.__version__


H_MASTER_UUID = "X-DEVPI-MASTER-UUID"
H_PRIMARY_UUID = "X-DEVPI-PRIMARY-UUID"
SIMPLE_API_V1_JSON = "application/vnd.pypi.simple.v1+json"


API_VERSION = "2"

meta_headers = {
    "X-DEVPI-API-VERSION": API_VERSION,
    "X-DEVPI-SERVER-VERSION": server_version}


INSTALLER_USER_AGENT = r"([^ ]* )*(distribute|setuptools|pip|pex|uv)/.*"
INSTALLER_USER_AGENT_REGEXP = re.compile(INSTALLER_USER_AGENT)


def _select_simple_content_type(request):
    offers = request.accept.acceptable_offers([
        "text/html", SIMPLE_API_V1_JSON])
    if offers:
        return offers[0][0]
    return "text_html"


def is_simple_json(request):
    return _select_simple_content_type(request) == SIMPLE_API_V1_JSON


def is_requested_by_installer(request):
    return INSTALLER_USER_AGENT_REGEXP.match(request.user_agent or "")


def is_simple_json_or_requested_by_installer(request):
    return is_simple_json(request) or is_requested_by_installer(request)


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
        'HTTPError', (HTTPException,), dict(
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
        'HTTPError', (HTTPException,), dict(
            code=401, title=msg))
    err = err()
    err.headers.add('WWW-Authenticate', 'Basic realm="pypi"')
    err.headers.add('location', request.route_url("/+login"))
    raise err


class HTTPResponse(HTTPSuccessful):
    body_template = None
    comment = None
    detail = None

    def __init__(self, **kw):
        Response.__init__(self, **kw)
        Exception.__init__(self)


def apiresult(code, message=None, result=None, type=None):  # noqa: A002
    d = dict()
    if result is not None:
        assert type is not None
        d["result"] = result
        d["type"] = type
    if message:
        d["message"] = message
    data = json.dumps(d, indent=2) + "\n"
    headers = {"content-type": "application/json"}
    return HTTPResponse(body=data, status=code, headers=headers)


def apireturn(code, message=None, result=None, type=None):  # noqa: A002
    raise apiresult(code, message=message, result=result, type=type)


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
        tag = f"[req{next(req_count)}]"
        log = thread_push_log(tag)
        try:
            request.log = log
            log.info("%s %s" % (request.method, request.path))
            now = time()
            response = handler(request)
            duration = time() - now
            rheaders = response.headers
            serial = rheaders.get("X-DEVPI-SERIAL")
            rheaders.update(meta_headers)
            uuid, primary_uuid = nodeinfo.make_uuid_headers()
            rheaders["X-DEVPI-UUID"] = uuid
            rheaders[H_MASTER_UUID] = primary_uuid
            rheaders[H_PRIMARY_UUID] = primary_uuid

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
    warnings.warn(
        "The make_uuid_headers function is deprecated, "
        "use config.nodeinfo.make_uuid_headers instead",
        DeprecationWarning,
        stacklevel=2,
    )
    if not isinstance(nodeinfo, NodeInfo):
        nodeinfo = NodeInfo(nodeinfo)
    return nodeinfo.make_uuid_headers()


def tween_keyfs_transaction(handler, registry):
    keyfs = registry["xom"].keyfs
    is_replica = registry["xom"].is_replica()

    def request_tx_handler(request):
        write = is_mutating_http_method(request.method) and not is_replica
        transaction_method = (
            keyfs.write_transaction
            if write else
            keyfs.read_transaction)
        with transaction_method() as tx:
            threadlog.debug("in-transaction %s", tx.at_serial)
            try:
                response = handler(request)
            except KeyfsTimeoutError as e:
                msg = lazy_format_exception_only(e)
                threadlog.error(
                    "Keyfs timeout: %s", msg)
                return HTTPInternalServerError(msg)
        set_header_devpi_serial(response, tx)
        return response
    return request_tx_handler


def set_header_devpi_serial(response, tx):
    if "X-DEVPI-SERIAL" in response.headers:
        # already set explicitly
        return
    if tx.commit_serial is not None:
        serial = tx.commit_serial
    else:
        serial = tx.at_serial
    response.headers["X-DEVPI-SERIAL"] = str(serial)


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
            "serverdir": str(config.server_path),
            "uuid": self.xom.config.nodeinfo["uuid"],
            "versioninfo": dict(self.request.registry["devpi_version_info"]),
            "server-code": os.path.dirname(devpi_server.__file__),
            "host": config.args.host,
            "port": config.args.port,
            "outside-url": config.outside_url,
            "serial": self.xom.keyfs.get_current_serial(),
            "last-commit-timestamp": self.xom.keyfs.get_last_commit_timestamp(),
            "event-serial": self.xom.keyfs.notifier.read_event_serial(),
            "event-serial-timestamp": self.xom.keyfs.notifier.get_event_serial_timestamp(),
            "event-serial-in-sync-at": self.xom.keyfs.notifier.event_serial_in_sync_at,
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
            status["master-url"] = config.primary_url.url
            status["master-uuid"] = config.get_primary_uuid()
            status["master-serial"] = self.xom.replica_thread.get_primary_serial()
            status["master-serial-timestamp"] = self.xom.replica_thread.get_primary_serial_timestamp()
            status["master-contacted-at"] = self.xom.replica_thread.primary_contacted_at
            status["update-from-master-at"] = self.xom.replica_thread.update_from_primary_at
            status["primary-url"] = config.primary_url.url
            status["primary-uuid"] = config.get_primary_uuid()
            status["primary-serial"] = self.xom.replica_thread.get_primary_serial()
            status["primary-serial-timestamp"] = self.xom.replica_thread.get_primary_serial_timestamp()
            status["replica-started-at"] = self.xom.replica_thread.started_at
            status["primary-contacted-at"] = self.xom.replica_thread.primary_contacted_at
            status["update-from-primary-at"] = self.xom.replica_thread.update_from_primary_at
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
    check_event_serial = True
    if status["role"] == "REPLICA":
        replica_sync_status = "fatal"
        if status["replica-started-at"] is not None:
            last_update = status["update-from-primary-at"]
            if last_update is None:
                if (now - status["replica-started-at"]) > 300:
                    msgs.append(dict(status="fatal", msg="No contact to primary for more than 5 minutes"))
                elif (now - status["replica-started-at"]) > 60:
                    msgs.append(dict(status="warn", msg="No contact to primary for more than 1 minute"))
            elif (now - last_update) > 300:
                msgs.append(dict(status="fatal", msg="No update from primary for more than 5 minutes"))
            elif (now - last_update) > 60:
                msgs.append(dict(status="warn", msg="No update from primary for more than 1 minute"))
            else:
                replica_sync_status = "warn"
        replica_in_sync_at = status["replica-in-sync-at"]
        replica_in_sync_delta = None if replica_in_sync_at is None else (now - replica_in_sync_at)
        primary_serial = status["primary-serial"]
        if primary_serial is not None and primary_serial > status["serial"]:
            if replica_in_sync_delta is None or replica_in_sync_delta > 3600:
                msgs.append(dict(status=replica_sync_status, msg="Replica is behind primary for more than 60 minutes"))
            elif (now - replica_in_sync_at) > 300:
                msgs.append(dict(status="warn", msg="Replica is behind primary for more than 5 minutes"))
            else:
                check_event_serial = False
        elif len(status["replication-errors"]):
            msgs.append(dict(status="fatal", msg="Unhandled replication errors"))
    if check_event_serial and status["serial"] > status["event-serial"]:
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
        elif (sync_at is None and last_processed is None) or (sync_at is not None and sync_at > 21600):
            msgs.append(dict(status="fatal", msg="The event processing hasn't been in sync for more than 6 hours"))
        elif sync_at is not None and sync_at > 3600:
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


TOXRESULT_UPLOAD_FORBIDDEN = (
    "No permission to upload tox results. "
    "You can use the devpi test --no-upload option to skip the upload.")


@attrs.define(frozen=True)
class ToxResultHandling:
    _block: bool = attrs.field(default=False, alias="_block")
    _skip: bool = attrs.field(default=False, alias="_skip")
    msg: None | str = None

    def block(self, msg=TOXRESULT_UPLOAD_FORBIDDEN):
        return ToxResultHandling(_block=True, msg=msg)

    def skip(self, msg=None):
        return ToxResultHandling(_skip=True, msg=msg)


@hookimpl(trylast=True)
def devpiserver_on_toxresult_store(request, tox_result_handling):
    return tox_result_handling


@hookimpl(trylast=True)
def devpiserver_on_toxresult_upload_forbidden(request, tox_result_handling):
    return tox_result_handling


def version_in_filename(version, filename):
    if version is None:
        # no version set, so skip check
        return True
    if version in filename:
        return True
    # PEP 427 escaped wheels
    return re.sub(r"[^\w\d.]+", "_", version, flags=re.UNICODE) in filename


class PyPIView:
    def __init__(self, request):
        self.request = request
        self.context = request.context
        xom = request.registry['xom']
        self.xom = xom
        self.log = request.log

    @lazy
    def auth(self):
        return Auth(self.xom, self.xom.config.get_auth_secret())

    @property
    def model(self):
        return self.xom.model

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
        if orig_request.matched_route is None:
            return HTTPForbidden()
        root_factory = orig_request.matched_route.factory or root_factory
        orig_request.context = root_factory(orig_request)
        with RequestContext(orig_request):
            return self._auth_check_request(orig_request)

    #
    # attach test results to release files
    #

    @view_config(
        route_name="/{user}/{index}/+f/{relpath:.*}",
        request_method="POST")
    def post_toxresult(self):
        if not self.request.has_permission("toxresult_upload"):
            default_tox_result_handling = ToxResultHandling().block(TOXRESULT_UPLOAD_FORBIDDEN)
            tox_result_handling = self.xom.config.hook.devpiserver_on_toxresult_upload_forbidden(
                request=self.request, tox_result_handling=default_tox_result_handling)
        else:
            stage = self.context.stage
            relpath = self.request.path_info.strip("/")
            link = stage.get_link_from_entrypath(relpath)
            if link is None or link.rel != "releasefile":
                apireturn(404, message="no release file found at %s" % relpath)
            default_tox_result_handling = ToxResultHandling()
            tox_result_handling = self.xom.config.hook.devpiserver_on_toxresult_store(
                request=self.request, tox_result_handling=default_tox_result_handling)
        if tox_result_handling._block:
            apireturn(403, tox_result_handling.msg)
        if tox_result_handling._skip:
            apireturn(200, tox_result_handling.msg)
        # the getjson call validates that we got valid json
        getjson(self.request)
        # but we store the original body
        toxresultdata = self.request.body
        hashes = get_hashes(toxresultdata)
        tox_link = stage.store_toxresult(link, toxresultdata, hashes=hashes)
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
        return 'HTTP_X_DEVPI_ABSOLUTE_URLS' in self.request.environ

    @view_config(route_name="/{user}/{index}/+simple/{project}")
    def simple_list_project_redirect(self):
        """
        PEP 503:
        the repository SHOULD redirect the URLs without a /
        to add a / to the end
        """
        request = self.request
        abort_if_invalid_project(request, request.matchdict["project"])
        if is_simple_json_or_requested_by_installer(request):
            # for performance reasons we return results directly for
            # known installers
            return self.simple_list_project()
        response = HTTPFound(location=self.request.route_url(
            "/{user}/{index}/+simple/{project}/",
            user=self.context.username,
            index=self.context.index,
            project=self.context.project))
        response.vary = set(["Accept", "User-Agent"])
        return response

    @view_config(route_name="/{user}/{index}/+simple/{project}/")
    def simple_list_project(self):
        request = self.request
        abort_if_invalid_project(request, request.matchdict["project"])
        project = self.context.project
        # we only serve absolute links so we don't care about the route's slash
        stage = self.context.stage
        requested_by_installer = is_simple_json_or_requested_by_installer(request)
        try:
            result = stage.SimpleLinks(
                stage.get_simplelinks(
                    project, sorted_links=not requested_by_installer))
        except stage.UpstreamError as e:
            threadlog.error(e.msg)
            abort(request, 502, e.msg)

        if not result:
            # access of verified_project will trigger 404 if not found
            self.request.context.verified_project  # noqa: B018

        if requested_by_installer:
            # we don't need the extra stuff on the simple page for pip
            embed_form = False
            blocked_index = None
        else:
            # only mere humans need to know and do more
            whitelist_info = stage.get_mirror_whitelist_info(project)
            embed_form = whitelist_info['has_mirror_base']
            blocked_index = whitelist_info['blocked_by_mirror_whitelist']
        content_type = _select_simple_content_type(self.request)
        if content_type == SIMPLE_API_V1_JSON:
            app_iter = self._simple_list_project_json_v1(
                stage, project, result, embed_form, blocked_index)
        else:
            app_iter = self._simple_list_project(
                stage, project, result, embed_form, blocked_index)
        response = Response(
            app_iter=buffered_iterator(app_iter),
            content_type=content_type,
            vary=set(["Accept", "User-Agent"]))
        if stage.ixconfig['type'] == 'mirror':
            serial = stage.key_projsimplelinks(project).get().get("serial")
            if serial is not None and serial > 0:
                response.headers["X-PYPI-LAST-SERIAL"] = str(serial)
        if result.stale:
            response.cache_expires()
        return response

    def _makeurl_factory(self):
        if self._use_absolute_urls:
            # for joinpath we need the root url
            application_url = self.request.application_url
            if not application_url.endswith("/"):
                application_url = application_url + "/"
            url = URL(application_url)

            def make_url(href):
                return url.joinpath(href)
        else:
            # for relpath we need the path of the current page
            url = URL(self.request.path_info)

            def make_url(href):
                return URL(url.relpath("/" + href))

        return make_url

    def _simple_list_project(self, stage, project, result, embed_form, blocked_index):
        title = "%s: links for %s" % (stage.name, project)
        yield (
            '<!DOCTYPE html><html lang="en"><head><title>%s</title></head><body><h1>%s</h1>\n'
            % (title, title)
        ).encode("utf-8")

        if embed_form:
            yield self._index_refresh_form(stage, project).encode("utf-8")

        if blocked_index:
            yield ("<p><strong>INFO:</strong> Because this project isn't in "
                   "the <code>mirror_whitelist</code>, no releases from "
                   "<strong>%s</strong> are included.</p>"
                   % blocked_index).encode('utf-8')

        make_url = self._makeurl_factory()

        for link in result:
            stage = "/".join(link.href.split("/", 2)[:2])
            attribs = 'href="%s"' % make_url(link.href).url
            if link.require_python is not None:
                attribs += ' data-requires-python="%s"' % escape(link.require_python)
            if link.yanked is not None and link.yanked is not False:
                yanked = "" if link.yanked is True else link.yanked
                attribs += ' data-yanked="%s"' % escape(yanked)
            data = dict(stage=stage, attribs=attribs, key=link.key)
            yield "{stage} <a {attribs}>{key}</a><br>\n".format(**data).encode("utf-8")

        yield "</body></html>".encode("utf-8")

    def _simple_list_project_json_v1(self, stage, project, result, embed_form, blocked_index):
        yield (f'{{"meta":{{"api-version":"1.0"}},"name":"{project}","files":[').encode("utf-8")

        make_url = self._makeurl_factory()

        first = True
        for link in result:
            url = make_url(link.href)
            data = {
                "filename": link.key,
                "url": url.url_nofrag,
                "hashes": {url.hash_type: url.hash_value} if url.hash_type else {}}
            if link.require_python is not None:
                data["requires-python"] = link.require_python
            if link.yanked is not None and link.yanked is not False:
                data["yanked"] = link.yanked
            info = json.dumps(data, indent=None, sort_keys=False)
            if first:
                yield f'{info}'.encode("utf-8")
                first = False
            else:
                yield f',{info}'.encode("utf-8")

        yield "]}".encode("utf-8")

    def _index_refresh_form(self, stage, project):
        url = self.request.route_url(
            "/{user}/{index}/+simple/{project}/refresh",
            user=self.context.username, index=self.context.index,
            project=project)
        title = "Refresh" if stage.ixconfig["type"] == "mirror" else "Refresh mirror links"
        submit = '<input name="refresh" type="submit" value="%s">' % title
        return '<form action="%s" method="post">%s</form>' % (url, submit)

    @view_config(route_name="/{user}/{index}/+simple")
    def simple_list_all_redirect(self):
        """
        PEP 503:
        the repository SHOULD redirect the URLs without a /
        to add a / to the end
        """
        request = self.request
        if is_simple_json_or_requested_by_installer(request):
            # for performance reasons we return results directly for
            # known installers
            return self.simple_list_all()
        response = HTTPFound(location=request.route_url(
            "/{user}/{index}/+simple/",
            user=self.context.username,
            index=self.context.index))
        response.vary = set(["User-Agent"])
        return response

    @view_config(request_method="GET", route_name="/{user}/{index}/+simple/")
    def simple_list_all(self):
        self.log.info("starting +simple")
        stage = self.context.stage
        try:
            # list is called to force iteration over all results in this
            # try/except block
            stage_results = list(stage.list_projects())
        except stage.UpstreamError as e:
            threadlog.error(e.msg)
            abort(self.request, 502, e.msg)
        # at this point we are sure we can produce the data without
        # depending on remote networks
        content_type = _select_simple_content_type(self.request)
        if content_type == SIMPLE_API_V1_JSON:
            app_iter = self._simple_list_all_json_v1(stage_results)
        elif is_requested_by_installer(self.request):
            app_iter = self._simple_list_all_installer(stage_results)
        else:
            app_iter = self._simple_list_all(stage.name, stage_results)
        return Response(
            app_iter=buffered_iterator(app_iter),
            content_type=content_type,
            vary=set(["Accept", "User-Agent"]))

    def _simple_list_all(self, stage_name, stage_results):
        title = f"{stage_name}: simple list (including inherited indices)"
        yield f'<!DOCTYPE html><html lang="en"><head><title>{title}</title></head><body><h1>{title}</h1>'.encode()
        last_index = len(stage_results) - 1
        seen = set()
        for index, (stage, names) in enumerate(stage_results):
            h2 = stage.name
            bases = getattr(stage, "ixconfig", {}).get("bases")
            if bases:
                h2 += " (bases: %s)" % ",".join(bases)
            yield f"<h2>{h2}</h2>".encode("utf-8")
            for name in sorted(names):
                if name not in seen:
                    yield f'<a href="{name}/">{name}</a><br>\n'.encode()
                    if index != last_index:
                        seen.add(name)
        yield "</body></html>".encode("utf-8")

    def _simple_list_all_installer(self, stage_results):
        yield b'<!DOCTYPE html><html lang="en"><body>'
        last_index = len(stage_results) - 1
        seen = set()
        for index, (stage, names) in enumerate(stage_results):
            for name in names:
                if name not in seen:
                    yield f'<a href="{name}/">{name}</a>\n'.encode("utf-8")
                    if index != last_index:
                        seen.add(name)
        yield "</body></html>".encode("utf-8")

    def _simple_list_all_json_v1(self, stage_results):
        yield '{"meta":{"api-version":"1.0"},"projects":['.encode("utf-8")
        last_index = len(stage_results) - 1
        seen = set()
        first = True
        for index, (stage, names) in enumerate(stage_results):
            for name in names:
                if name not in seen:
                    info = f'{{"name":"{name}"}}'
                    if first:
                        yield f'{info}'.encode("utf-8")
                        first = False
                    else:
                        yield f',{info}'.encode("utf-8")
                    if index != last_index:
                        seen.add(name)
        yield ']}'.encode("utf-8")

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
                    if value not in ixconfig[key]:
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
        if 'error_on_noop' in self.request.params and oldconfig == json:
            apireturn(400, message="The requested modifications resulted in no changes")
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
            name = pushdata.pop("name")
            version = pushdata.pop("version")
        except KeyError:
            return apiresult(
                400, f"there are no files for {name} {version} on stage {stage.name}"
            )

        # first, get all the links related to the source "to push" release
        try:
            linkstore = stage.get_linkstore_perstage(name, version)
        except stage.MissesRegistration:
            return apiresult(
                400, f"there are no files for {name} {version} on stage {stage.name}"
            )
        rels = {'releasefile', 'doczip', 'toxresult'}
        no_docs = pushdata.pop("no_docs", False)
        only_docs = pushdata.pop("only_docs", False)
        if no_docs and only_docs:
            return apiresult(400, "can't use 'no_docs' and 'only_docs' together")
        if no_docs:
            rels.remove('doczip')
        elif only_docs:
            rels = {'doczip'}
        links = defaultdict(list)
        for link in linkstore.get_links():
            if link.rel not in rels:
                continue
            links[link.rel].append(link)
        for rel in links:
            links[rel] = sorted(links[rel], key=attrgetter("basename"))
        if not any(links.values()):
            self.log.info("%s: no files for version %s %s", stage.name, name, version)
            return apiresult(404, f"no release/files found for {name} {version}")

        if not request.has_permission("pkg_read"):
            abort(request, 403, "package read forbidden")

        targetindex = pushdata.pop("targetindex", None)
        metadata = linkstore.metadata
        if targetindex is None:
            return self._push_external(name, version, links, metadata, pushdata)
        if pushdata:
            keys = ", ".join(sorted(pushdata.keys()))
            return apiresult(400, f"unknown additional options: {keys}")
        return self._push_internal(name, version, links, metadata, targetindex)

    def _push_internal(self, name, version, links, metadata, targetindex):
        request = self.request
        results = []
        parts = targetindex.split("/")
        if len(parts) != 2:
            return apiresult(400, "targetindex not in format user/index")
        target_stage = self.context.getstage(*parts)
        auth_user = request.authenticated_userid
        self.log.debug("targetindex %r, auth_user %r", targetindex, auth_user)
        if not request.has_permission("upload", context=target_stage):
            return apiresult(
                401, f"user {auth_user!r} cannot upload to {targetindex!r}"
            )
        self._set_versiondata_dict(target_stage, metadata)
        results.append((200, "register", name, version, "->", target_stage.name))
        try:
            results.extend(self._push_links(links, target_stage, name, version))
        except target_stage.NonVolatile as e:
            return apiresult(
                409, f"{e.link.basename} already exists in non-volatile index"
            )
        except BadGateway as e:
            return apiresult(502, e.args[0])
        return apiresult(200, result=results, type="actionlog")

    def _push_external(self, name, version, links, metadata, pushdata):
        results = []
        register_project = pushdata.pop("register_project", False)
        posturl = pushdata["posturl"]
        pypiauth = f"{pushdata['username']}:{pushdata['password']}".encode()
        extra_headers = {"Authorization": f"Basic {b64encode(pypiauth).decode()}"}
        # prepare metadata for submission
        metadata[":action"] = "submit"
        ok_codes = {HTTPStatus.OK, HTTPStatus.CREATED}
        if register_project:
            self.log.info("registering %s %s to %s", name, version, posturl)
            try:
                r = self.xom.http.post(
                    posturl, data=metadata, extra_headers=extra_headers
                )
                r.close()
            except Exception as e:  # noqa: BLE001
                exc_msg = lazy_format_exception_only(e)
                results.append((-1, "exception on register:", str(exc_msg)))
                return apiresult(502, result=results, type="actionlog")
            self.log.debug("register returned: %s", r.status_code)
            results.append((r.status_code, "register", name, version))
            proceed = r.status_code in ok_codes | {HTTPStatus.GONE}
        else:
            proceed = True
        if proceed:
            for link in links["releasefile"]:
                results.extend(
                    self._push_external_release(link, metadata, posturl, extra_headers)
                )
            if doczip_link := next(iter(links["doczip"]), None):
                results.extend(
                    self._push_external_doczip(
                        doczip_link, metadata, posturl, extra_headers
                    )
                )
        return (
            apiresult(200, result=results, type="actionlog")
            if results[-1][0] in ok_codes
            else apiresult(502, result=results, type="actionlog")
        )

    def _push_external_release(self, link, metadata, posturl, extra_headers):
        results = []
        entry = link.entry
        file_metadata = metadata.copy()
        file_metadata[":action"] = "file_upload"
        basename = link.basename
        pyver, filetype = get_pyversion_filetype(basename)
        file_metadata["filetype"] = filetype
        file_metadata["pyversion"] = pyver
        file_metadata[f"{link.best_available_hash_type}_digest"] = (
            link.best_available_hash_value
        )
        content = entry.file_get_content()
        self.log.info("sending %s to %s, metadata %s", basename, posturl, file_metadata)
        try:
            r = self.xom.http.post(
                posturl,
                data=file_metadata,
                extra_headers=extra_headers,
                files={"content": (basename, content)},
            )
        except Exception as e:  # noqa: BLE001
            exc_msg = lazy_format_exception_only(e)
            results.append((-1, "exception on release upload:", str(exc_msg)))
            return results
        self.log.debug("send finished, status: %s", r.status_code)
        # ignore response body on success
        text = "" if r.status_code in (200, 201) else r.text
        results.append((r.status_code, "upload", entry.relpath, text))
        r.close()
        return results

    def _push_external_doczip(self, link, metadata, posturl, extra_headers):
        results = []
        doc_metadata = metadata.copy()
        doc_metadata[":action"] = "doc_upload"
        name = doc_metadata["name"]
        doczip = link.entry.file_get_content()
        try:
            r = self.xom.http.post(
                posturl,
                data=doc_metadata,
                extra_headers=extra_headers,
                files={"content": (f"{name}.zip", doczip)},
            )
            r.close()
        except Exception as e:  # noqa: BLE001
            exc_msg = lazy_format_exception_only(e)
            results.append((-1, "exception on documentation upload:", str(exc_msg)))
            return results
        self.log.debug("send finished, status: %s", r.status_code)
        results.append((r.status_code, "docfile", name))
        return results

    def _push_links(self, links, target_stage, name, version):
        stage = self.context.stage
        for link in links.get("releasefile", ()):
            entry = link.entry
            logs = link.get_logs()
            del link
            if should_fetch_remote_file(entry, self.request.headers):
                for _data in iter_fetch_remote_file(stage, entry, entry.url):
                    pass
                # re-get entry for current metadata which might have
                # added hashes if a file had to be streamed from a remote
                entry = self.xom.filestore.get_file_entry(entry.relpath)
            with entry.file_open_read() as f:
                new_link = target_stage.store_releasefile(
                    name, version, entry.basename, f,
                    hashes=entry.hashes,
                    last_modified=entry.last_modified)
            new_link.add_logs(
                x for x in logs
                if x.get('what') != 'overwrite')
            new_link.add_log(
                'push',
                self.request.authenticated_userid,
                src=self.context.stage.name,
                dst=target_stage.name)
            new_entry = new_link.entry
            yield (200, "store_releasefile", new_entry.relpath)
            # also store all dependent tox results
            tstore = target_stage.get_linkstore_perstage(name, version)
            for toxlink in links["toxresult"]:
                if toxlink.for_entrypath == entry.relpath:
                    ref_link = tstore.get_links(entrypath=new_entry.relpath)[0]
                    with toxlink.entry.file_open_read() as f:
                        tlink = target_stage.store_toxresult(
                            ref_link, f, hashes=toxlink.entry.hashes)
                    tlink.add_logs(
                        x for x in toxlink.get_logs()
                        if x.get('what') != 'overwrite')
                    tlink.add_log(
                        'push',
                        self.request.authenticated_userid,
                        src=self.context.stage.name,
                        dst=target_stage.name)
                    yield (200, "store_toxresult", tlink.relpath)
        for link in links.get("doczip", ()):
            with link.entry.file_open_read() as doczip:
                new_link = target_stage.store_doczip(
                    name, version, doczip, hashes=link.entry.hashes)
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
        if action not in ("doc_upload", "file_upload"):
            abort_submit(request, 400, "action %r not supported" % action)
        try:
            _content = request.POST["content"]
        except KeyError:
            abort_submit(request, 400, "content file field not found")
        content_filename = _content.filename
        content_file = get_seekable_content_or_file(_content.file)
        hashes = get_hashes(content_file)
        name = ensure_unicode(request.POST["name"])
        # version may be empty on plain doczip uploads
        version = ensure_unicode(request.POST.get("version") or "")
        project = normalize_name(name)

        if action == "file_upload":
            # we only check for release files if version is
            # contained in the filename because for doczip files
            # we construct the filename ourselves anyway.
            if not version_in_filename(version, content_filename):
                abort_submit(
                    request, 400,
                    "filename %r does not contain version %r" % (
                        content_filename, version))

            abort_if_invalid_filename(request, name, content_filename)
            self._update_versiondata_form(stage, request.POST)
            try:
                link = stage.store_releasefile(
                    project, version,
                    content_filename, content_file, hashes=hashes)
            except stage.NonVolatile as e:
                if e.link.matches_checksum(content_file):
                    abort_submit(
                        request, 200,
                        "Upload of identical file to non volatile index.",
                        level="info")
                abort_submit(
                    request, 409,
                    "%s already exists in non-volatile index" % (
                        content_filename,))
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
            try:
                link = stage.store_doczip(
                    project, version, content_file, hashes=hashes)
            except stage.MissesVersion as e:
                abort_submit(
                    request, 400,
                    "%s" % e)
            except stage.NonVolatile as e:
                if e.link.matches_checksum(content_file):
                    abort_submit(
                        request, 200,
                        "Upload of identical file to non volatile index.",
                        level="info")
                abort_submit(
                    request, 409,
                    "%s already exists in non-volatile index" % (
                        content_filename,))
        link.add_log(
            'upload', request.authenticated_userid, dst=stage.name)
        return Response("")

    def _get_versiondata_from_form(self, stage, form, skip_missing=False):
        metadata = {}
        for key in stage.metadata_keys:
            if skip_missing and key not in form:
                continue
            elif key in stage.metadata_list_fields:
                val = [
                    ensure_unicode(item)
                    for item in form.getall(key) if item]
            else:
                val = form.get(key, "")
                if val == "UNKNOWN":
                    val = ""
                assert isinstance(val, str), val
            metadata[key] = val
        return metadata

    def _update_versiondata_form(self, stage, form):
        # first we only get metadata without any default values for
        # missing keys
        new_metadata = self._get_versiondata_from_form(
            stage, form, skip_missing=True)
        # now we have the name and version and look for existing metadata
        metadata = get_mutable_deepcopy(stage.get_versiondata_perstage(
            new_metadata["name"], new_metadata["version"]))
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
        self.log.info(
            "%s: got submit release info %r",
            stage.name, metadata["name"])

    #
    #  per-project and version data
    #

    @view_config(route_name="installer_simple", accept="text/html")
    @view_config(route_name="installer_simple", accept="application/vnd.pypi.simple.v1+json")
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
            apireturn(403, "project %r is on non-volatile index %s" % (
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
            view_verdata["+shadowing"] = [
                self._make_view_verdata(x)
                for x in shadowing]
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
        if not entry.meta:
            abort(request, 410, "file existed, deleted in later serial")

        if json_preferred(request):
            entry_data = get_mutable_deepcopy(entry.meta)
            apireturn(200, type="releasefilemeta", result=entry_data)

        # getting the stage from context will cause 404 if stage is deleted
        stage = self.context.stage

        url = URL(entry.url)

        file_exists = entry.file_exists()
        if entry.last_modified is None or not file_exists:
            # We check whether we should serve the file directly
            # or redirect to the external URL
            if stage.use_external_url:
                # The file is in a mirror and either deleted or not
                # yet downloaded. Redirect to external url
                # we need to add auth back to the url, as httpx doesn't include it
                # in the response url
                # we do it in _pkgserv now to avoid storing the credentials
                # in the database and avoid changes in the db when mirror_url changes.
                mirror_url_auth = getattr(stage, "mirror_url_auth", {})
                url = url.replace(**mirror_url_auth)
                return HTTPFound(location=url.url)
            if stage.ixconfig['type'] != "mirror" and not file_exists and not self.xom.is_replica():
                # return error when private file is missing and not in
                # replica mode, otherwise fall through to fetch file
                abort(self.request, 404, "no such file")

        if not request.has_permission("pkg_read"):
            abort(request, 403, "package read forbidden")

        try:
            if should_fetch_remote_file(entry, request.headers):
                app_iter = iter_fetch_remote_file(stage, entry, url)
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
            # FileIter will close the file
            return Response(
                app_iter=FileIter(entry.file_open_read()), headers=headers)

    @view_config(route_name="/{user}/{index}/+e/{relpath:.*}")
    def mirror_pkgserv(self):
        relpath = self._relpath_from_request()
        # when a release is deleted from a mirror, we update the metadata,
        # hence the key won't exist anymore, but we don't delete the file.
        # We want people to notice that condition by returning a 404, but
        # they can still recover the deleted release from the filesystem
        # manually in case they need it.
        key = self.xom.filestore.get_key_from_relpath(relpath)
        if key is None or not key.exists():
            abort(self.request, 404, "no such file")
        entry = self.xom.filestore.get_file_entry_from_key(key)
        return self._pkgserv(entry)

    @view_config(route_name="/{user}/{index}/+f/{relpath:.*}")
    def stage_pkgserv(self):
        relpath = self._relpath_from_request()
        entry = self.xom.filestore.get_file_entry(relpath)
        if entry is None:
            abort(self.request, 404, "no such file")
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
        elif not entry.meta:
            abort(self.request, 410, "file %r existed, deleted in later serial" % relpath)
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

    @view_config(route_name="/{user}/{index}", accept="application/vnd.pypi.simple.v1+json", request_method="GET")
    @view_config(route_name="/{user}/{index}/", accept="application/vnd.pypi.simple.v1+json", request_method="GET")
    def index_pep691_get(self):
        return self.simple_list_all()

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

    @view_config(route_name="/{user}", request_method="PATCH")
    @view_config(route_name="/{user}/", request_method="PATCH")
    def user_patch(self):
        request = self.request
        kvdict = getjson(request)
        user = self.context.user
        if len(keys := kvdict.keys()) == 1 and "password" in keys:
            if not self.request.has_permission("user_modify_password"):
                return apiresult(
                    403, f"no permission to change password for user {user}"
                )
        elif not self.request.has_permission("user_modify"):
            return apiresult(403, f"no permission to modify user {user}")
        password = kvdict.get("password")
        try:
            user.modify(**kvdict)
        except InvalidUserconfig as e:
            return apiresult(400, message=", ".join(e.messages))
        if password is not None:
            return apiresult(
                200,
                "user updated, new proxy auth",
                type="userpassword",
                result=self.auth.new_proxy_auth(
                    user.name, password=password, request=request
                ),
            )
        return apiresult(200, "user updated")

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
                apireturn(403, "user %r has non-volatile index: %s" % (
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
        "X-Accel-Buffering": "no",  # disable buffering in nginx
        "content-type": content_type}
    if "last-modified" in r.headers:
        headers["last-modified"] = r.headers["last-modified"]
    if "content-length" in r.headers:
        headers["content-length"] = str(r.headers["content-length"])
    return headers


class FileStreamer:
    def __init__(self, f, entry, response):
        self.hash_type = entry.best_available_hash_type
        self.hash_types = entry.default_hash_types
        self._hashes = entry.hashes
        self.relpath = entry.relpath
        self.response = response
        self.error = None
        self.f = f

    def __iter__(self):
        filesize = 0
        running_hashes = RunningHashes(self.hash_type, *self.hash_types)
        running_hashes.start()
        content_size = self.response.headers.get("content-length")

        yield _headers_from_response(self.response)

        data_iter = self.response.iter_raw(10240)
        while 1:
            data = next(data_iter, None)
            if data is None:
                break
            filesize += len(data)
            for rh in running_hashes._running_hashes:
                rh.update(data)
            self.f.write(data)
            yield data

        self.hashes = running_hashes.digests

        if content_size and int(content_size) != filesize:
            raise ValueError(
                "%s: got %s bytes of %r from remote, expected %s" % (
                    self.relpath, filesize, self.response.url, content_size))
        if self._hashes:
            err = self.hashes.exception_for(self._hashes, self.relpath)
            if err is not None:
                raise err


def iter_cache_remote_file(stage, entry, url):
    # we get and cache the file and some http headers from remote
    xom = stage.xom
    url = URL(url)

    with contextlib.ExitStack() as cstack:
        r = stage.http.stream(cstack, "GET", url, allow_redirects=True)
        if r.status_code != 200:
            r.close()
            msg = f"error {r.status_code} getting {url}"
            threadlog.error(msg)
            raise BadGateway(msg, code=r.status_code, url=url)
        f = cstack.enter_context(entry.file_new_open())
        file_streamer = FileStreamer(f, entry, r)
        threadlog.info("reading remote: %r, target %s", URL(r.url), entry.relpath)

        try:
            yield from file_streamer
        except Exception as err:
            threadlog.error(str(err))
            raise

        if not entry.has_existing_metadata():
            with xom.keyfs.write_transaction(allow_restart=True):
                if entry.readonly:
                    entry = xom.filestore.get_file_entry_from_key(entry.key)
                entry.file_set_content(
                    f,
                    last_modified=r.headers.get("last-modified", None),
                    hash_spec=entry._hash_spec,
                    hashes=file_streamer.hashes)
                if entry.project:
                    stage = xom.model.getstage(entry.user, entry.index)
                    # for mirror indexes this makes sure the project is in the database
                    # as soon as a file was fetched
                    stage.add_project_name(entry.project)
                # on Windows we need to close the file
                # before the transaction closes
                f.close()
        else:
            # the file was downloaded before but locally removed, so put
            # it back in place without creating a new serial
            with xom.keyfs.filestore_transaction():
                entry.file_set_content_no_meta(f, hashes=file_streamer.hashes)
                threadlog.debug(
                    "put missing file back into place: %s", entry._storepath)
                # on Windows we need to close the file
                # before the transaction closes
                f.close()


def iter_remote_file_replica(stage, entry, url):
    xom = stage.xom
    replication_errors = xom.replica_thread.shared_data.errors
    # construct primary URL with param
    primary_url = xom.config.primary_url.joinpath(entry.relpath).url
    if not url:
        threadlog.warn("missing private file: %s" % entry.relpath)
    else:
        threadlog.info("replica doesn't have file: %s", entry.relpath)

    with contextlib.ExitStack() as cstack:
        r = stage.http.stream(
            cstack,
            "GET",
            primary_url,
            allow_redirects=True,
            extra_headers={xom.replica_thread.H_REPLICA_FILEREPL: "YES"},
        )
        if r.status_code != 200:
            r.close()
            msg = f"{primary_url}: received {r.status_code} from primary"
            if not url:
                threadlog.error(msg)
                raise BadGateway(msg)
            # try to get from original location
            headers = {}
            url = URL(url)
            username = url.username or ""
            password = url.password or ""
            if username or password:
                url = url.replace(username=None, password=None)
                auth = f"{username}:{password}".encode()
                headers["Authorization"] = f"Basic {b64encode(auth).decode()}"
            r = xom.http.stream(
                cstack, "GET", url, allow_redirects=True, extra_headers=headers
            )
            if r.status_code != 200:
                r.close()
                msg = f"{msg}\n{url}: received {r.status_code}"
                threadlog.error(msg)
                raise BadGateway(msg)
        cstack.callback(r.close)
        f = cstack.enter_context(entry.file_new_open())
        file_streamer = FileStreamer(f, entry, r)

        try:
            yield from file_streamer
        except Exception as err:  # noqa: BLE001 - we have to convert all exceptions
            # the file we got is different, so we fail
            raise BadGateway(str(err)) from err

        with xom.keyfs.filestore_transaction():
            entry.file_set_content_no_meta(f, hashes=file_streamer.hashes)
            # on Windows we need to close the file
            # before the transaction closes
            f.close()
            threadlog.debug("put missing file back into place: %s", entry._storepath)
        # in case there were errors before, we can now remove them
        replication_errors.remove(entry)


def iter_fetch_remote_file(stage, entry, url):
    if not stage.xom.is_replica():
        yield from iter_cache_remote_file(stage, entry, url)
    else:
        yield from iter_remote_file_replica(stage, entry, url)


def url_for_entrypath(request, entrypath):
    path = entrypath.split("#", 1)[0]
    parts = path.split("/")
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
        abort_submit(request, 400, f"{filename!r} is not a valid archive name")
    if normalize_name(filename).startswith(normalize_name(name)):
        return
    abort_submit(
        request, 400, "filename %r does not match project name %r" % (
            filename, name))


def abort_if_invalid_project(request, project):
    try:
        if isinstance(project, bytes):
            project.decode("ascii")
        else:
            project.encode("ascii")
    except (UnicodeEncodeError, UnicodeDecodeError):
        abort(request, 400, "unicode project names not allowed")
