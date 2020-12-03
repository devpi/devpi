# coding: utf-8
from __future__ import unicode_literals
from defusedxml.xmlrpc import DefusedExpatParser
from devpi_common.metadata import Version
from devpi_common.metadata import get_pyversion_filetype
from devpi_common.metadata import get_sorted_versions
from devpi_common.validation import normalize_name
from devpi_common.viewhelp import iter_toxresults
from devpi_server.log import threadlog as log
from devpi_server.readonly import SeqViewReadonly
from devpi_server.views import StatusView, url_for_entrypath
from devpi_web.description import get_description
from devpi_web.doczip import Docs, unpack_docs
from devpi_web.indexing import is_project_cached
from devpi_web.main import navigation_version
from email.utils import parsedate
from operator import attrgetter, itemgetter
from py.xml import html
try:
    from pyramid.compat import decode_path_info
except ImportError:
    # pyramid is >= 2.0, which means we can assume Python 3
    # see PEP 3333 for why we encode WSGI PATH_INFO to latin-1 before
    # decoding it to utf-8
    def decode_path_info(path):
        return path.encode('latin-1').decode('utf-8')
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
    def resolved_version(self):
        version = self.version
        if version == 'latest' and self._versions:
            version = self._versions[0]
        elif version == 'stable' and self._stable_versions:
            version = self._stable_versions[0]
        return version

    @reify
    def _versions(self):
        return get_sorted_versions(
            self.stage.list_versions_perstage(self.project),
            stable=False)

    @reify
    def versions(self):
        versions = self._versions
        if not versions:
            raise HTTPNotFound("The project %s does not exist." % self.project)
        return versions

    @reify
    def _stable_versions(self):
        return get_sorted_versions(self._versions, stable=True)

    @reify
    def stable_versions(self):
        if not self._versions:
            raise HTTPNotFound("The project %s does not exist." % self.project)
        versions = self._stable_versions
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


def get_doc_info(context, request, version=None, check_content=True):
    relpath = request.matchdict['relpath']
    if not relpath:
        raise HTTPFound(location="index.html")
    name = context.project
    if version is None:
        version = context.version
    if version == 'latest':
        versions = context.versions
    elif version == 'stable':
        versions = context.stable_versions
    else:
        versions = [version]
    doc_path = None
    for doc_version in versions:
        try:
            linkstore = context.stage.get_linkstore_perstage(name, doc_version)
        except context.stage.MissesRegistration:
            continue
        links = linkstore.get_links(rel='doczip')
        if not links:
            continue
        doc_path = unpack_docs(context.stage, name, doc_version, links[0].entry)
        if doc_path.isdir():
            break
    if doc_path is None or not doc_path.isdir():
        if version == 'stable':
            raise HTTPNotFound("No stable documentation available.")
        raise HTTPNotFound("No documentation available.")
    doc_path = doc_path.join(relpath)
    if check_content and not doc_path.check():
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
    response = FileResponse(str(doc_info['doc_path']))
    if context.version in ('latest', 'stable'):
        response.cache_expires()
    return response


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
    version_links = []
    latest_doc_info = get_doc_info(context, request, version='latest', check_content=False)
    if latest_doc_info['doc_version'] != doc_info['doc_version']:
        version_links.append(dict(
            title="Latest documentation",
            url=request.route_url(
                "docviewroot", user=stage.user.name, index=stage.index,
                project=name, version='latest', relpath="index.html")))
    try:
        stable_doc_info = get_doc_info(context, request, version='stable', check_content=False)
        if stable_doc_info['doc_version'] != doc_info['doc_version'] and stable_doc_info['doc_version'] != latest_doc_info['doc_version']:
            version_links.append(dict(
                title="Stable documentation",
                url=request.route_url(
                    "docviewroot", user=stage.user.name, index=stage.index,
                    project=name, version='stable', relpath="index.html")))
    except (HTTPFound, HTTPNotFound):
        pass
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
            project=name, version=version,
            relpath=doc_info['relpath'], _query=request.query_string),
        version_mismatch=doc_info['version_mismatch'],
        version_links=version_links,
        doc_version=doc_info['doc_version'])


@notfound_view_config(renderer="templates/notfound.pt")
def notfound(request):
    if request.method == 'POST':
        request.response.status = 404
        return dict(msg=request.exception)
    path = decode_path_info(request.environ['PATH_INFO'] or '/')
    registry = request.registry
    mapper = registry.queryUtility(IRoutesMapper)
    if mapper is not None and path.endswith('/') and '+simple' not in path:
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
        if entry.hash_spec:
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
                fileinfo['toxresults_state'] = get_toxresults_state(toxresults)
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
            status = 'unknown'
            if not toxenv.setup['failed'] and not toxenv.test['failed'] and toxenv.test['commands']:
                status = 'passed'
            elif toxenv.setup['failed'] or toxenv.test['failed']:
                status = 'failed'
            info = dict(
                basename=toxlink.basename,
                _key="-".join(toxenv.key),
                host=toxenv.host,
                platform=toxenv.platform,
                envname=toxenv.envname,
                setup=toxenv.setup,
                test=toxenv.test,
                status=status)
            if toxenv.pyversion:
                info["pyversion"] = toxenv.pyversion
            result.append(info)
    return result


def get_toxresults_state(toxresults):
    if not toxresults:
        return
    toxstates = set(x['status'] for x in toxresults)
    if 'failed' in toxstates:
        return 'failed'
    if toxstates == set(['passed']):
        return 'passed'
    return 'unknown'


def get_docs_info(request, stage, linkstore):
    if stage.ixconfig['type'] == 'mirror':
        return
    links = linkstore.get_links(rel='doczip')
    if not links:
        return
    name, ver = normalize_name(linkstore.project), linkstore.version
    doc_path = unpack_docs(stage, name, ver, links[0].entry)
    if doc_path.isdir():
        return dict(
            title="%s-%s" % (name, ver),
            url=request.route_url(
                "docviewroot", user=stage.user.name, index=stage.index,
                project=name, version=ver, relpath="index.html"))


def get_user_info(context, request, user):
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
    return dict(
        _user=user,
        title=username,
        user_name=username,
        user_title=user.get('title', None),
        user_description=user.get('description', None),
        user_email=user.get('email', None),
        user_url=request.route_url(
            "/{user}", user=username),
        indexes=indexes)


@view_config(
    route_name='root',
    renderer='templates/root.pt')
def root(context, request):
    rawusers = sorted(
        (x.get() for x in context.model.get_userlist()),
        key=itemgetter('username'))
    users = []
    for user in rawusers:
        users.append(get_user_info(context, request, user))
    return dict(
        _context=context,
        users=users)


@view_config(
    route_name="/{user}", accept="text/html", request_method="GET",
    renderer="templates/user.pt")
def user_get(context, request):
    user = context.user.get()
    return dict(
        _context=context,
        user=get_user_info(context, request, user))


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
        _context=context,
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
        whitelist.extend(sorted(stage.ixconfig.get('mirror_whitelist', [])))
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
            docs=get_docs_info(request, stage, linkstore),
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
        linkstore = context.stage.get_linkstore_perstage(name, version)
        docs = get_docs_info(request, context.stage, linkstore)
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
    stage = context.stage
    latest_verdata = {}
    latest_version = stage.get_latest_version_perstage(context.project)
    if latest_version is not None:
        latest_verdata = stage.get_versiondata_perstage(
            context.project, latest_version)
    return dict(
        _context=context,
        title="%s/: %s versions" % (context.stage.name, context.project),
        blocked_by_mirror_whitelist=whitelist_info['blocked_by_mirror_whitelist'],
        latest_version=latest_version,
        latest_url=request.route_url(
            "/{user}/{index}/{project}/{version}",
            user=user, index=index, project=name, version='latest'),
        latest_version_data=latest_verdata,
        versions=versions)


@view_config(
    route_name="/{user}/{index}/{project}/{version}",
    accept="text/html", request_method="GET",
    renderer="templates/version.pt")
def version_get(context, request):
    """ Show version for the precise stage, ignores inheritance. """
    context = ContextWrapper(context)
    name = context.verified_project
    stage = context.stage
    version = context.resolved_version
    try:
        verdata = context.get_versiondata(version=version, perstage=True)
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
    docs = get_docs_info(request, stage, linkstore)
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
    cmp_version = Version(version)
    if context._stable_versions:
        stable_version = Version(context._stable_versions[0])
        url = request.route_url(
            "/{user}/{index}/{project}/{version}",
            user=context.username, index=context.index,
            project=context.project, version='stable')
        if cmp_version.is_prerelease():
            nav_links.append(dict(
                title="Stable version available",
                css_class="warning",
                url=url))
        elif stable_version != cmp_version:
            nav_links.append(dict(
                title="Newer version available",
                css_class="severe",
                url=url))
    return dict(
        _context=context,
        title="%s/: %s-%s metadata and description" % (stage.name, name, version),
        content=get_description(stage, name, version),
        summary=verdata.get("summary"),
        resolved_version=version,
        nav_links=nav_links,
        infos=infos,
        metadata_list_fields=frozenset(
            py.xml.escape(x)
            for x in getattr(stage, 'metadata_list_fields', ())),
        files=files,
        blocked_by_mirror_whitelist=whitelist_info['blocked_by_mirror_whitelist'],
        show_toxresults=show_toxresults,
        make_toxresults_url=functools.partial(
            request.route_url, "toxresults",
            user=context.username, index=context.index,
            project=context.project, version=version),
        make_toxresult_url=functools.partial(
            request.route_url, "toxresult",
            user=context.username, index=context.index,
            project=context.project, version=version))


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
        _context=context,
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
        _context=context,
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
            break
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
        # if params['page'] is not in batching range,
        # URL is broken, then let's go back to first page of batching
        current = 0
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
                entry = docs[sub_data['text_path']]
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
            path = data['path']
            more_results = result['info']['collapsed_counts'][path]
            if more_results:
                new_params = make_more_url_params(self.params, path)
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
            fields, operator = data
        else:
            fields = data
            operator = "and"
        log.debug("xmlrpc_search {0}".format((fields, operator)))
        return dict(fields=fields, operator=operator)

    @view_config(
        route_name="/{user}/{index}/", request_method="POST",
        content_type="text/xml", is_mutating=False)
    def xmlrpc_search(self):
        try:
            query = self.query_from_xmlrpc(self.request.body)
            search_index = self.request.registry['search_index']
            context = ContextWrapper(self.request.context)
            hits = search_index.query_packages(query, list(context.stage.sro()))
            response = dumps((hits,), methodresponse=1, encoding='utf-8')
        except Exception as e:
            log.exception("Error in xmlrpc_search")
            response = dumps(Fault(1, repr(e)), encoding='utf-8')
        return Response(response)


def make_more_url_params(params, path):
    new_params = dict(params)
    if 'page' in new_params:
        del new_params['page']
    new_params['query'] = "%s path:%s" % (params['query'], path)
    return new_params
