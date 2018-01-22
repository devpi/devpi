# coding: utf-8
from __future__ import unicode_literals
from defusedxml.xmlrpc import DefusedExpatParser
from devpi_common.metadata import get_pyversion_filetype
from devpi_common.metadata import get_sorted_versions
from devpi_common.validation import normalize_name
from devpi_common.viewhelp import iter_toxresults
from devpi_server.log import threadlog as log
from devpi_server.readonly import SeqViewReadonly
from devpi_server.views import StatusView, url_for_entrypath
from devpi_web.description import get_description
from devpi_web.doczip import Docs, get_unpack_path
from devpi_web.indexing import is_project_cached
from devpi_web.main import navigation_version
from email.utils import parsedate
from operator import attrgetter, itemgetter
from py.xml import html
from pyramid.compat import decode_path_info
from pyramid.decorator import reify
from pyramid.httpexceptions import HTTPBadGateway, HTTPError
from pyramid.httpexceptions import HTTPFound, HTTPNotFound
from pyramid.httpexceptions import default_exceptionresponse_view
from pyramid.interfaces import IRoutesMapper
from pyramid.response import FileResponse, Response
from pyramid.view import notfound_view_config, view_config
from time import gmtime
try:
    from xmlrpc.client import Fault, Unmarshaller, dumps
except ImportError:
    from xmlrpclib import Fault, Unmarshaller, dumps
import functools
import json
import py

seq_types = (list, tuple, SeqViewReadonly)


class ContextWrapper(object):
    def __init__(self, context):
        self.context = context

    def __getattr__(self, name):
        return getattr(self.context, name)

    @reify
    def versions(self):
        versions = self.stage.list_versions(self.project)
        if not versions:
            raise HTTPNotFound("The project %s does not exist." % self.project)
        return get_sorted_versions(versions)

    @reify
    def stable_versions(self):
        versions = self.stage.list_versions(self.project)
        if not versions:
            raise HTTPNotFound("The project %s does not exist." % self.project)
        versions = get_sorted_versions(versions, stable=True)
        if not versions:
            raise HTTPNotFound("The project %s has no stable release." % self.project)
        return versions

    @reify
    def linkstore(self):
        try:
            return self.stage.get_linkstore_perstage(self.project, self.version)
        except self.stage.MissesRegistration:
            raise HTTPNotFound(
                "%s-%s is not registered" % (self.project, self.version))


def get_doc_info(context, request):
    relpath = request.matchdict['relpath']
    if not relpath:
        raise HTTPFound(location="index.html")
    name = context.project
    version = context.version
    if version == 'latest':
        versions = context.versions
    elif version == 'stable':
        versions = context.stable_versions
    else:
        versions = [version]
    for doc_version in versions:
        doc_path = get_unpack_path(context.stage, name, doc_version)
        if doc_path.check():
            break
    if not doc_path.check():
        if version == 'stable':
            raise HTTPNotFound("No stable documentation available.")
        raise HTTPNotFound("No documentation available.")
    doc_path = doc_path.join(relpath)
    if not doc_path.check():
        raise HTTPNotFound("File %s not found in documentation." % relpath)
    return dict(
        doc_path=doc_path,
        relpath=relpath,
        doc_version=doc_version,
        version_mismatch=doc_version != navigation_version(context))


@view_config(route_name="docroot", request_method="GET")
def doc_serve(context, request):
    """ Serves the raw documentation files. """
    context = ContextWrapper(context)
    doc_info = get_doc_info(context, request)
    return FileResponse(str(doc_info['doc_path']))


@view_config(
    route_name="docviewroot",
    request_method="GET",
    renderer="templates/doc.pt")
def doc_show(context, request):
    """ Shows the documentation wrapped in an iframe """
    context = ContextWrapper(context)
    stage = context.stage
    name, version = context.project, context.version
    doc_info = get_doc_info(context, request)
    return dict(
        title="%s-%s Documentation" % (name, version),
        base_url=request.route_url(
            "docroot", user=stage.user.name, index=stage.index,
            project=name, version=version, relpath=''),
        baseview_url=request.route_url(
            "docviewroot", user=stage.user.name, index=stage.index,
            project=name, version=version, relpath=''),
        url=request.route_url(
            "docroot", user=stage.user.name, index=stage.index,
            project=name, version=version, relpath=doc_info['relpath']),
        version_mismatch=doc_info['version_mismatch'],
        doc_version=doc_info['doc_version'])


@notfound_view_config(renderer="templates/notfound.pt")
def notfound(request):
    if request.method == 'POST':
        request.response.status = 404
        return dict(msg=request.exception)
    path = decode_path_info(request.environ['PATH_INFO'] or '/')
    registry = request.registry
    mapper = registry.queryUtility(IRoutesMapper)
    if mapper is not None and path.endswith('/'):
        # redirect URLs with a trailing slash to URLs without one, if there
        # is a matching route
        nonslashpath = path.rstrip('/')
        for route in mapper.get_routes():
            if route.match(nonslashpath) is not None:
                qs = request.query_string
                if qs:
                    qs = '?' + qs
                return HTTPFound(location=request.application_url + nonslashpath + qs)
    request.response.status = 404
    return dict(msg=request.exception)


@view_config(context=HTTPError, renderer="templates/error.pt")
def error_view(request):
    if 'text/html' in request.accept:
        request.response.status = request.exception.status
        return dict(
            title=request.exception.title,
            status=request.exception.status,
            msg=request.exception)
    else:
        return default_exceptionresponse_view(request.context, request)


dist_file_types = {
    'sdist': 'Source',
    'bdist_dumb': '"dumb" binary',
    'bdist_rpm': 'RPM',
    'bdist_wininst': 'MS Windows installer',
    'bdist_msi': 'MS Windows MSI installer',
    'bdist_egg': 'Python Egg',
    'bdist_dmg': 'OS X Disk Image',
    'bdist_wheel': 'Python Wheel'}


def sizeof_fmt(num):
    for x in ['bytes', 'KB', 'MB', 'GB']:
        if num < 1024.0:
            return (num, x)
        num /= 1024.0
    return (num, 'TB')


def format_timetuple(tt):
    if tt is not None:
        return "{0}-{1:02d}-{2:02d} {3:02d}:{4:02d}:{5:02d}".format(*tt)


def format_timestamp(ts, unset_value=None):
    if ts is None:
        ts = unset_value
    try:
        if ts is not None:
            ts = format_timetuple(gmtime(ts)[:6])
    except (ValueError, TypeError):
        pass
    return ts


_what_map = dict(
    overwrite="Replaced",
    push="Pushed",
    upload="Uploaded")


def make_history_view_item(request, log_item):
    result = {}
    result['what'] = _what_map.get(log_item['what'], log_item['what'])
    result['who'] = log_item['who']
    if log_item['what'] != 'overwrite':
        result['when'] = format_timetuple(log_item['when'])
    for key in ('dst', 'src'):
        if key in log_item:
            result[key] = dict(
                title=log_item[key],
                href=request.stage_url(log_item[key]))
    if 'count' in log_item:
        result['count'] = log_item['count']
    return result


def get_files_info(request, linkstore, show_toxresults=False):
    files = []
    filedata = linkstore.get_links(rel='releasefile')
    if not filedata:
        log.warn("project %r version %r has no files",
                 linkstore.project, linkstore.version)
    for link in sorted(filedata, key=attrgetter('basename')):
        url = url_for_entrypath(request, link.entrypath)
        entry = link.entry
        if entry.eggfragment:
            url += "#egg=%s" % entry.eggfragment
        elif entry.hash_spec:
            url += "#" + entry.hash_spec
        py_version, file_type = get_pyversion_filetype(link.basename)
        if py_version == 'source':
            py_version = ''
        size = ''
        if entry.file_exists():
            size = "%.0f %s" % sizeof_fmt(entry.file_size())
        try:
            history = [
                make_history_view_item(request, x)
                for x in link.get_logs()]
        except AttributeError:
            history = []
        last_modified = format_timetuple(parsedate(entry.last_modified))
        fileinfo = dict(
            title=link.basename,
            url=url,
            basename=link.basename,
            hash_spec=entry.hash_spec,
            dist_type=dist_file_types.get(file_type, ''),
            py_version=py_version,
            last_modified=last_modified,
            history=history,
            size=size)
        if show_toxresults:
            toxresults = get_toxresults_info(linkstore, link)
            if toxresults:
                fileinfo['toxresults'] = toxresults
        files.append(fileinfo)
    return files


def load_toxresult(link):
    data = link.entry.file_get_content().decode("utf-8")
    return json.loads(data)


def get_toxresults_info(linkstore, for_link, newest=True):
    result = []
    toxlinks = linkstore.get_links(rel="toxresult", for_entrypath=for_link)
    for toxlink, toxenvs in iter_toxresults(toxlinks, load_toxresult, newest=newest):
        if toxenvs is None:
            log.error("Couldn't parse test results %s." % toxlink)
            continue
        for toxenv in toxenvs:
            info = dict(
                basename=toxlink.basename,
                _key="-".join(toxenv.key),
                host=toxenv.host,
                platform=toxenv.platform,
                envname=toxenv.envname,
                setup=toxenv.setup,
                test=toxenv.test,
                failed=toxenv.failed)
            if toxenv.pyversion:
                info["pyversion"] = toxenv.pyversion
            result.append(info)
    return result


def get_docs_info(request, stage, metadata):
    if stage.ixconfig['type'] == 'mirror':
        return
    name, ver = normalize_name(metadata["name"]), metadata["version"]
    doc_path = get_unpack_path(stage, name, ver)
    if doc_path.exists():
        return dict(
            title="%s-%s" % (name, ver),
            url=request.route_url(
                "docviewroot", user=stage.user.name, index=stage.index,
                project=name, version=ver, relpath="index.html"))


@view_config(
    route_name='root',
    renderer='templates/root.pt')
def root(context, request):
    rawusers = sorted(
        (x.get() for x in context.model.get_userlist()),
        key=itemgetter('username'))
    users = []
    for user in rawusers:
        username = user['username']
        indexes = []
        for index in sorted(user.get('indexes', [])):
            stagename = "%s/%s" % (username, index)
            stage = context.model.getstage(stagename)
            indexes.append(dict(
                _ixconfig=stage.ixconfig,
                title=stagename,
                index_name=index,
                index_title=stage.ixconfig.get('title', None),
                index_description=stage.ixconfig.get('description', None),
                url=request.stage_url(stagename)))
        users.append(dict(
            _user=user,
            title=username,
            user_name=username,
            user_title=user.get('title', None),
            user_description=user.get('description', None),
            user_email=user.get('email', None),
            indexes=indexes))
    return dict(users=users)


@view_config(
    route_name="/{user}/{index}", accept="text/html", request_method="GET",
    renderer="templates/index.pt")
def index_get(context, request):
    context = ContextWrapper(context)
    stage = context.stage
    permissions = []
    bases = []
    packages = []
    whitelist = []
    result = dict(
        title="%s index" % stage.name,
        simple_index_url=request.simpleindex_url(stage),
        permissions=permissions,
        bases=bases,
        packages=packages,
        whitelist=whitelist,
        index_name=stage.name,
        index_title=stage.ixconfig.get('title', None),
        index_description=stage.ixconfig.get('description', None))
    if stage.ixconfig['type'] == 'mirror':
        return result

    if hasattr(stage, "ixconfig"):
        whitelist.extend(sorted(stage.ixconfig['mirror_whitelist']))
        for base in stage.ixconfig["bases"]:
            bases.append(dict(
                title=base,
                url=request.stage_url(base),
                simple_url=request.simpleindex_url(base)))
        acls = [
            (key[4:], stage.ixconfig[key])
            for key in stage.ixconfig
            if key.startswith('acl_')]
        for permission, principals in sorted(acls):
            groups = []
            special = []
            users = []
            for principal in principals:
                if principal.startswith(':'):
                    if principal.endswith(':'):
                        special.append(dict(title=principal[1:-1]))
                    else:
                        groups.append(dict(title=principal[1:]))
                else:
                    users.append(dict(title=principal))
            permissions.append(dict(
                title=permission,
                groups=groups,
                special=special,
                users=users))

    for project in stage.list_projects_perstage():
        version = stage.get_latest_version_perstage(project)
        verdata = stage.get_versiondata_perstage(project, version)
        try:
            name, ver = normalize_name(verdata["name"]), verdata["version"]
        except KeyError:
            log.error("metadata for project %r empty: %s, skipping",
                      project, verdata)
            continue
        show_toxresults = (stage.ixconfig['type'] != 'mirror')
        linkstore = stage.get_linkstore_perstage(name, ver)
        packages.append(dict(
            info=dict(
                title="%s-%s" % (name, ver),
                url=request.route_url(
                    "/{user}/{index}/{project}/{version}",
                    user=stage.user.name, index=stage.index,
                    project=name, version=ver)),
            make_toxresults_url=functools.partial(
                request.route_url, "toxresults",
                user=stage.user.name, index=stage.index,
                project=name, version=ver),
            files=get_files_info(request, linkstore, show_toxresults),
            docs=get_docs_info(request, stage, verdata),
            _version_data=verdata))
    packages.sort(key=lambda x: x["info"]["title"])

    return result


@view_config(
    route_name="/{user}/{index}/{project}",
    accept="text/html", request_method="GET",
    renderer="templates/project.pt")
def project_get(context, request):
    context = ContextWrapper(context)
    try:
        releaselinks = context.stage.get_releaselinks(context.verified_project)
        stage_versions = context.stage.list_versions_perstage(context.verified_project)
    except context.stage.UpstreamError as e:
        log.error(e.msg)
        raise HTTPBadGateway(e.msg)
    version_info = {}
    seen = set()
    for release in releaselinks:
        user, index = release.entrypath.split("/", 2)[:2]
        name, version = release.project, release.version
        if not version or version == 'XXX':
            continue
        seen_key = (user, index, name, version)
        if seen_key in seen:
            continue
        version_info[version] = dict(
            index_title="%s/%s" % (user, index),
            index_url=request.stage_url(user, index),
            title=version,
            url=request.route_url(
                "/{user}/{index}/{project}/{version}",
                user=user, index=index, project=name, version=version),
            docs=None,
            _release=release)
        seen.add(seen_key)
    user = context.username
    index = context.stage.index
    index_title = "%s/%s" % (user, index)
    name = context.verified_project
    index_url = request.stage_url(user, index)
    for version in stage_versions:
        verdata = context.stage.get_versiondata_perstage(name, version)
        docs = get_docs_info(
            request, context.stage, verdata)
        if not docs:
            continue
        if version not in version_info:
            version_info[version] = dict(
                index_title=index_title,
                index_url=index_url,
                title=version,
                url=request.route_url(
                    "/{user}/{index}/{project}/{version}",
                    user=user, index=index, project=name, version=version),
                docs=docs,
                _release=None)
        else:
            version_info[version]['docs'] = docs
    versions = []
    for version in get_sorted_versions(version_info):
        versions.append(version_info[version])
    if hasattr(context.stage, 'get_mirror_whitelist_info'):
        whitelist_info = context.stage.get_mirror_whitelist_info(context.project)
    else:
        whitelist_info = dict(
            has_mirror_base=context.stage.has_mirror_base(context.project),
            blocked_by_mirror_whitelist=None)
    return dict(
        title="%s/: %s versions" % (context.stage.name, context.project),
        blocked_by_mirror_whitelist=whitelist_info['blocked_by_mirror_whitelist'],
        versions=versions)


@view_config(
    route_name="/{user}/{index}/{project}/{version}",
    accept="text/html", request_method="GET",
    renderer="templates/version.pt")
def version_get(context, request):
    """ Show version for the precise stage, ignores inheritance. """
    context = ContextWrapper(context)
    name, version = context.verified_project, context.version
    stage = context.stage
    try:
        verdata = context.get_versiondata(perstage=True)
    except stage.UpstreamError as e:
        log.error(e.msg)
        raise HTTPBadGateway(e.msg)
    infos = []
    skipped_keys = frozenset(
        ("description", "home_page", "name", "summary", "version"))
    for key, value in sorted(verdata.items()):
        if key in skipped_keys or key.startswith('+'):
            continue
        if isinstance(value, seq_types):
            if not len(value):
                continue
            value = html.ul([html.li(x) for x in value]).unicode()
        else:
            if not value:
                continue
            value = py.xml.escape(value)
        infos.append((py.xml.escape(key), value))
    show_toxresults = (stage.ixconfig['type'] != 'mirror')
    linkstore = stage.get_linkstore_perstage(name, version)
    files = get_files_info(request, linkstore, show_toxresults)
    docs = get_docs_info(request, stage, verdata)
    home_page = verdata.get("home_page")
    nav_links = []
    if docs:
        nav_links.append(dict(
            title="Documentation",
            url=docs['url']))
    if home_page:
        nav_links.append(dict(
            title="Homepage",
            url=home_page))
    nav_links.append(dict(
        title="Simple index",
        url=request.route_url(
            "/{user}/{index}/+simple/{project}",
            user=context.username, index=context.index, project=context.project)))
    if hasattr(stage, 'get_mirror_whitelist_info'):
        whitelist_info = stage.get_mirror_whitelist_info(name)
    else:
        whitelist_info = dict(
            has_mirror_base=stage.has_mirror_base(name),
            blocked_by_mirror_whitelist=False)
    if whitelist_info['has_mirror_base']:
        for base in reversed(list(stage.sro())):
            if base.ixconfig["type"] != "mirror":
                continue
            mirror_web_url_fmt = base.ixconfig.get("mirror_web_url_fmt")
            if not mirror_web_url_fmt:
                continue
            nav_links.append(dict(
                title="%s page" % base.ixconfig.get("title", "Mirror"),
                url=mirror_web_url_fmt.format(name=name)))
    return dict(
        title="%s/: %s-%s metadata and description" % (stage.name, name, version),
        content=get_description(stage, name, version),
        summary=verdata.get("summary"),
        nav_links=nav_links,
        infos=infos,
        files=files,
        blocked_by_mirror_whitelist=whitelist_info['blocked_by_mirror_whitelist'],
        show_toxresults=show_toxresults,
        make_toxresults_url=functools.partial(
            request.route_url, "toxresults",
            user=context.username, index=context.index,
            project=context.project, version=context.version),
        make_toxresult_url=functools.partial(
            request.route_url, "toxresult",
            user=context.username, index=context.index,
            project=context.project, version=context.version))


@view_config(
    route_name="toxresults",
    accept="text/html", request_method="GET",
    renderer="templates/toxresults.pt")
def toxresults(context, request):
    context = ContextWrapper(context)
    linkstore = context.linkstore
    basename = request.matchdict['basename']
    toxresults = get_toxresults_info(
        linkstore, linkstore.get_links(basename=basename)[0], newest=False)
    return dict(
        title="%s/: %s-%s toxresults" % (
            context.stage.name, context.project, context.version),
        toxresults=toxresults,
        make_toxresult_url=functools.partial(
            request.route_url, "toxresult",
            user=context.username, index=context.index,
            project=context.project, version=context.version, basename=basename))


@view_config(
    route_name="toxresult",
    accept="text/html", request_method="GET",
    renderer="templates/toxresult.pt")
def toxresult(context, request):
    context = ContextWrapper(context)
    linkstore = context.linkstore
    basename = request.matchdict['basename']
    toxresult = request.matchdict['toxresult']
    toxresults = [
        x for x in get_toxresults_info(
            linkstore,
            linkstore.get_links(basename=basename)[0], newest=False)
        if x['basename'] == toxresult]
    return dict(
        title="%s/: %s-%s toxresult %s" % (
            context.stage.name, context.project, context.version, toxresult),
        toxresults=toxresults)


@view_config(
    route_name="/+status",
    accept="text/html",
    renderer="templates/status.pt")
def statusview(request):
    status = StatusView(request)._status()
    replication_errors = []
    for index, error in enumerate(status.get('replication-errors', {}).values()):
        replication_errors.append(error)
        if index >= 10:
            replication_errors.append(dict(message="More than 10 replication errors."))
    _polling_replicas = status.get('polling_replicas', {})
    polling_replicas = []
    for replica_uuid in sorted(_polling_replicas):
        replica = _polling_replicas[replica_uuid]
        polling_replicas.append(dict(
            uuid=replica_uuid,
            remote_ip=replica.get('remote-ip', 'unknown'),
            outside_url=replica.get('outside-url', 'unknown'),
            serial=replica.get('serial', 'unknown'),
            in_request=replica.get('in-request', 'unknown'),
            last_request=format_timestamp(
                replica.get('last-request', 'unknown'))))
    return dict(
        msgs=request.status_info['msgs'],
        info=dict(
            uuid=status.get('uuid', 'unknown'),
            role=status.get('role', 'unknown'),
            outside_url=status.get('outside-url', 'unknown'),
            master_url=status.get('master-url'),
            master_uuid=status.get('master-uuid'),
            master_serial=status.get('master-serial'),
            master_serial_timestamp=format_timestamp(
                status.get('master-serial-timestamp'), unset_value="never"),
            replica_started_at=format_timestamp(
                status.get('replica-started-at')),
            replica_in_sync_at=format_timestamp(
                status.get('replica-in-sync-at'), unset_value="never"),
            update_from_master_at=format_timestamp(
                status.get('update-from-master-at'), unset_value="never"),
            serial=status.get('serial', 'unknown'),
            last_commit_timestamp=format_timestamp(
                status.get('last-commit-timestamp', 'unknown')),
            event_serial=status.get('event-serial', 'unknown'),
            event_serial_timestamp=format_timestamp(
                status.get('event-serial-timestamp', 'unknown')),
            event_serial_in_sync_at=format_timestamp(
                status.get('event-serial-in-sync-at', 'unknown'),
                unset_value="never")),
        replication_errors=replication_errors,
        polling_replicas=polling_replicas)


def batch_list(num, current, left=3, right=3):
    result = []
    if not num:
        return result
    if current >= num:
        raise ValueError("Current position (%s) can't be greater than total (%s)." % (current, num))
    result.append(0)
    first = current - left
    if first < 1:
        first = 1
    if first > 1:
        result.append(None)
    last = current + right + 1
    if last >= num:
        last = num - 1
    result.extend(range(first, last))
    if last < (num - 1):
        result.append(None)
    if num > 1:
        result.append(num - 1)
    return result


class SearchView:
    def __init__(self, request):
        self.request = request
        self._metadata = {}
        self._stage = {}
        self._docs = {}

    @reify
    def params(self):
        params = dict(self.request.params)
        params['query'] = params.get('query', '')
        try:
            params['page'] = int(params.get('page'))
        except TypeError:
            params['page'] = 1
        return params

    @reify
    def search_result(self):
        if not self.params['query']:
            return None
        search_index = self.request.registry['search_index']
        return search_index.query_projects(
            self.params['query'], page=self.params['page'])

    @reify
    def batch_links(self):
        batch_links = []
        if not self.search_result or not self.search_result['items']:
            return
        result_info = self.search_result['info']
        batch = batch_list(result_info['pagecount'], result_info['pagenum'] - 1)
        for index, item in enumerate(batch):
            if item is None:
                batch_links.append(dict(
                    title='…'))
            elif item == (self.params['page'] - 1):
                current = index
                batch_links.append({
                    'title': item + 1,
                    'class': 'current'})
            else:
                new_params = dict(self.params)
                new_params['page'] = item + 1
                batch_links.append(dict(
                    title=item + 1,
                    url=self.request.route_url(
                        'search',
                        _query=new_params)))
        if current < (len(batch_links) - 1):
            next = dict(batch_links[current + 1])
            next['title'] = 'Next'
            next['class'] = 'next'
            batch_links.append(next)
        else:
            batch_links.append({'class': 'next'})
        if current > 0:
            prev = dict(batch_links[current - 1])
            prev['title'] = 'Prev'
            prev['class'] = 'prev'
            batch_links.insert(0, prev)
        else:
            batch_links.insert(0, {'class': 'prev'})
        return batch_links

    def get_stage(self, path):
        if path not in self._stage:
            xom = self.request.registry['xom']
            user, index, name = path[1:].split('/')
            stage = xom.model.getstage(user, index)
            self._stage['path'] = stage
        return self._stage['path']

    def get_versiondata(self, stage, data):
        path = data['path']
        version = data.get('version')
        key = (path, version)
        if key not in self._metadata:
            name = data['name']
            metadata = {}
            if version and is_project_cached(stage, name):
                metadata = stage.get_versiondata(name, version)
                if metadata is None:
                    metadata = {}
            self._metadata[key] = metadata
        return self._metadata[key]

    def get_docs(self, stage, data):
        path = data['path']
        if path not in self._docs:
            self._docs[path] = Docs(stage, data['name'], data['doc_version'])
        return self._docs[path]

    def process_sub_hits(self, stage, sub_hits, data):
        search_index = self.request.registry['search_index']
        result = []
        for sub_hit in sub_hits:
            sub_data = sub_hit['data']
            text_type = sub_data['type']
            title = text_type.title()
            highlight = None
            if text_type == 'project':
                continue
            elif text_type in ('title', 'page'):
                docs = self.get_docs(stage, data)
                try:
                    entry = docs[sub_data['text_path']]
                except KeyError:
                    highlight = (
                        "Couldn't access documentation files for %s "
                        "version %s on %s. This is a bug. If you find a way "
                        "to reproduce this, please file an issue at: "
                        "https://github.com/devpi/devpi/issues" % (
                            data['name'], data['doc_version'], stage.name))
                else:
                    text = entry['text']
                    highlight = search_index.highlight(text, sub_hit.get('words'))
                title = sub_data.get('text_title', title)
                text_path = sub_data.get('text_path')
                if text_path:
                    sub_hit['url'] = self.request.route_url(
                        "docviewroot", user=data['user'], index=data['index'],
                        project=normalize_name(data['name']),
                        version=data['doc_version'],
                        relpath="%s.html" % text_path)
            elif text_type in ('keywords', 'description', 'summary'):
                metadata = self.get_versiondata(stage, data)
                if metadata is None:
                    continue
                text = metadata.get(text_type)
                if text is None:
                    continue
                highlight = search_index.highlight(text, sub_hit.get('words'))
                if 'version' in data:
                    sub_hit['url'] = self.request.route_url(
                        "/{user}/{index}/{project}/{version}",
                        user=data['user'], index=data['index'],
                        project=normalize_name(data['name']),
                        version=data['version'],
                        _anchor=text_type)
            else:
                log.error("Unknown type %s" % text_type)
                continue
            sub_hit['title'] = title
            sub_hit['highlight'] = highlight
            result.append(sub_hit)
        return result

    @reify
    def result(self):
        result = self.search_result
        if not result or not result['items']:
            return
        items = []
        for item in result['items']:
            data = item['data']
            stage = self.get_stage(data['path'])
            if stage is None:
                continue
            if 'version' in data:
                item['url'] = self.request.route_url(
                    "/{user}/{index}/{project}/{version}",
                    user=data['user'], index=data['index'],
                    project=normalize_name(data['name']),
                    version=data['version'])
                item['title'] = "%s-%s" % (data['name'], data['version'])
            else:
                item['url'] = self.request.route_url(
                    "/{user}/{index}/{project}",
                    user=data['user'], index=data['index'],
                    project=normalize_name(data['name']))
                item['title'] = data['name']
            item['sub_hits'] = self.process_sub_hits(
                stage, item['sub_hits'], data)
            more_results = result['info']['collapsed_counts'][data['path']]
            if more_results:
                new_params = dict(self.params)
                new_params['query'] = "%s path:%s" % (self.params['query'], data['path'])
                item['more_url'] = self.request.route_url(
                    'search',
                    _query=new_params)
                item['more_count'] = more_results
            items.append(item)
        if not items:
            return
        result['items'] = items
        return result

    @view_config(
        route_name='search',
        renderer='templates/search.pt')
    def __call__(self):
        return dict(
            query=self.params['query'],
            page=self.params['page'],
            batch_links=self.batch_links,
            result=self.result)

    @view_config(
        route_name='search_help',
        renderer='templates/search_help.pt')
    def search_help(self):
        return dict()

    def query_from_xmlrpc(self, body):
        unmarshaller = Unmarshaller()
        parser = DefusedExpatParser(unmarshaller)
        parser.feed(body)
        parser.close()
        (data, method) = (unmarshaller.close(), unmarshaller.getmethodname())
        if method != "search":
            raise ValueError("Unknown method '%s'." % method)
        if len(data) == 2:
            query, operator = data
        else:
            query = data
            operator = "and"
        log.debug("xmlrpc_search {0}".format((query, operator)))
        operator = operator.upper()
        if operator not in ('AND', 'OR', 'ANDNOT', 'ANDMAYBE', 'NOT'):
            raise ValueError("Unknown operator '%s'." % operator)
        if set(query.keys()).difference(['name', 'summary']):
            raise ValueError("Only 'name' and 'summary' allowed in query.")
        parts = []
        for key, field in (('name', 'project'), ('summary', 'summary')):
            value = query.get(key, [])
            if len(value) == 0:
                continue
            elif len(value) == 1:
                parts.append('(type:%s "%s")' % (field, value[0].replace('"', '')))
            else:
                raise ValueError("Only on value allowed for query.")
        return (" %s " % operator).join(parts)

    def search_index_packages(self, query):
        search_index = self.request.registry['search_index']
        result = search_index.query_projects(query, page=None)
        context = ContextWrapper(self.request.context)
        sro = dict((x.name, i) for i, x in enumerate(context.stage.sro()))
        # first gather basic info and only get most relevant info based on
        # stage resolution order
        name2stage = {}
        name2data = {}
        for item in result['items']:
            data = item['data']
            path = data['path']
            stage = self.get_stage(path)
            if stage is None:
                continue
            if stage.name not in sro:
                continue
            name = data['name']
            current_stage = name2stage.get(name)
            if current_stage is None or sro[stage.name] < sro[current_stage.name]:
                name2stage[name] = stage
                try:
                    score = item['score']
                except KeyError:
                    score = False
                    sub_hits = item.get('sub_hits')
                    if sub_hits:
                        score = sub_hits[0].get('score', False)
                name2data[name] = dict(
                    version=data.get('version', ''),
                    score=score)
        # then gather more info if available and build results
        hits = []
        for name, stage in name2stage.items():
            data = name2data[name]
            version = data['version']
            summary = '[%s]' % stage.name
            if version and is_project_cached(stage, name):
                metadata = stage.get_versiondata(name, version)
                version = metadata.get('version', version)
                summary += ' %s' % metadata.get('summary', '')
            hits.append(dict(
                name=name, summary=summary,
                version=version, _pypi_ordering=data['score']))
        return hits

    @view_config(
        route_name="/{user}/{index}/", request_method="POST",
        content_type="text/xml")
    def xmlrpc_search(self):
        try:
            query = self.query_from_xmlrpc(self.request.body)
            log.debug("xmlrpc_search {0}".format(query))
            hits = self.search_index_packages(query)
            response = dumps((hits,), methodresponse=1, encoding='utf-8')
        except Exception as e:
            log.exception("Error in xmlrpc_search")
            response = dumps(Fault(1, repr(e)), encoding='utf-8')
        return Response(response)
