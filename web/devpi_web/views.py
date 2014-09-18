# coding: utf-8
from __future__ import unicode_literals
from devpi_common.metadata import get_pyversion_filetype, splitbasename
from devpi_common.metadata import get_sorted_versions
from devpi_server.log import threadlog as log
from devpi_server.views import url_for_entrypath
from devpi_web.description import get_description
from devpi_web.doczip import Docs, get_unpack_path
from devpi_web.indexing import is_project_cached
from email.utils import parsedate
from operator import attrgetter, itemgetter
from py.xml import html
from pyramid.compat import decode_path_info
from pyramid.decorator import reify
from pyramid.httpexceptions import HTTPBadGateway, HTTPError
from pyramid.httpexceptions import HTTPFound, HTTPNotFound
from pyramid.httpexceptions import default_exceptionresponse_view
from pyramid.interfaces import IRoutesMapper
from pyramid.response import FileResponse
from pyramid.view import notfound_view_config, view_config
import functools
import json
import py


class ContextWrapper(object):
    def __init__(self, context):
        self.context = context

    def __getattr__(self, name):
        return getattr(self.context, name)

    @reify
    def stage(self):
        stage = self.model.getstage(self.username, self.index)
        if not stage:
            raise HTTPNotFound(
                "The stage %s/%s could not be found." % (self.username, self.index))
        return stage

    @reify
    def versions(self):
        versions = self.stage.list_versions(self.name)
        if not versions:
            raise HTTPNotFound("The project %s does not exist." % self.name)
        return get_sorted_versions(versions)

    @reify
    def verdata(self):
        verdata = self.stage.get_versiondata(self.name, self.version)
        if not verdata and self.versions:
            raise HTTPNotFound(
                "The version %s of project %s does not exist." % (
                    self.version, self.name))
        return verdata

    @reify
    def linkstore(self):
        return self.stage.get_linkstore_perstage(self.name, self.version)


def get_doc_path_info(context, request):
    relpath = request.matchdict['relpath']
    if not relpath:
        raise HTTPFound(location="index.html")
    name = context.name
    version = context.version
    if version != 'latest':
        versions = [version]
    else:
        versions = context.versions
    for version in versions:
        doc_path = get_unpack_path(context.stage, name, version)
        if doc_path.check():
            break
    if not doc_path.check():
        raise HTTPNotFound("No documentation available.")
    doc_path = doc_path.join(relpath)
    if not doc_path.check():
        raise HTTPNotFound("File %s not found in documentation." % relpath)
    return doc_path, relpath


@view_config(route_name="docroot", request_method="GET")
def doc_serve(context, request):
    """ Serves the raw documentation files. """
    context = ContextWrapper(context)
    doc_path, relpath = get_doc_path_info(context, request)
    return FileResponse(str(doc_path))


@view_config(
    route_name="docviewroot",
    request_method="GET",
    renderer="templates/doc.pt")
def doc_show(context, request):
    """ Shows the documentation wrapped in an iframe """
    context = ContextWrapper(context)
    stage = context.stage
    name, version = context.name, context.version
    doc_path, relpath = get_doc_path_info(context, request)
    return dict(
        title="%s-%s Documentation" % (name, version),
        base_url=request.route_url(
            "docroot", user=stage.user.name, index=stage.index,
            name=name, version=version, relpath=''),
        baseview_url=request.route_url(
            "docviewroot", user=stage.user.name, index=stage.index,
            name=name, version=version, relpath=''),
        url=request.route_url(
            "docroot", user=stage.user.name, index=stage.index,
            name=name, version=version, relpath=relpath))


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
                return HTTPFound(location=nonslashpath + qs)
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


_what_map = dict(
    overwrite="Replaced",
    push="Pushed",
    upload="Uploaded")


def make_history_view_item(request, log_item):
    result = {}
    result['what'] = _what_map.get(log_item['what'], log_item['what'])
    result['who'] = log_item['who']
    result['when'] = format_timetuple(log_item['when'])
    for key in ('dst', 'src'):
        if key in log_item:
            result[key] = dict(
                title=log_item[key],
                href=request.stage_url(log_item[key]))
    if 'md5' in log_item:
        result['md5'] = result
    return result


def get_files_info(request, linkstore, show_toxresults=False):
    files = []
    filedata = linkstore.get_links(rel='releasefile')
    if not filedata:
        log.warn("project %r version %r has no files",
                 linkstore.projectname, linkstore.version)
    for link in sorted(filedata, key=attrgetter('basename')):
        url = url_for_entrypath(request, link.entrypath)
        entry = link.entry
        if entry.eggfragment:
            url += "#egg=%s" % entry.eggfragment
        elif entry.md5:
            url += "#md5=%s" % entry.md5
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
            md5=entry.md5,
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


def _get_commands_info(commands):
    result = dict(
        failed=any(x["retcode"] != "0" for x in commands),
        commands=[])
    for command in commands:
        result["commands"].append(dict(
            failed=command["retcode"] != "0",
            command=" ".join(command["command"]),
            output=command["output"]))
    return result


def load_toxresult(link):
    data = link.entry.file_get_content().decode("utf-8")
    return json.loads(data)


def get_toxresults_info(linkstore, for_link, newest=True):
    result = []
    seen = set()
    toxlinks = linkstore.get_links(rel="toxresult", for_entrypath=for_link)
    for reflink in reversed(toxlinks):
        try:
            toxresult = load_toxresult(reflink)
            for envname in toxresult["testenvs"]:
                seen_key = (toxresult["host"], toxresult["platform"], envname)
                if seen_key in seen:
                    continue
                if newest:
                    seen.add(seen_key)
                env = toxresult["testenvs"][envname]
                info = dict(
                    basename=reflink.basename,
                    _key="-".join(seen_key),
                    host=toxresult["host"],
                    platform=toxresult["platform"],
                    envname=envname)
                info["setup"] = _get_commands_info(env.get("setup", []))
                try:
                    info["pyversion"] = env["python"]["version"].split(None, 1)[0]
                except KeyError:
                    pass
                info["test"] = _get_commands_info(env.get("test", []))
                info['failed'] = info["setup"]["failed"] or info["test"]["failed"]
                result.append(info)
        except Exception:
            log.exception("Couldn't parse test results %s." % reflink.basename)
    return result


def get_docs_info(request, stage, metadata):
    if stage.name == 'root/pypi':
        return
    name, ver = metadata["name"], metadata["version"]
    doc_path = get_unpack_path(stage, name, ver)
    if doc_path.exists():
        return dict(
            title="%s-%s" % (name, ver),
            url=request.route_url(
                "docviewroot", user=stage.user.name, index=stage.index,
                name=name, version=ver, relpath="index.html"))


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
            indexes.append(dict(
                title=stagename,
                url=request.stage_url(stagename)))
        users.append(dict(
            title=username,
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
    result = dict(
        title="%s index" % stage.name,
        simple_index_url=request.simpleindex_url(stage),
        permissions=permissions,
        bases=bases,
        packages=packages)
    if stage.name == "root/pypi":
        return result

    if hasattr(stage, "ixconfig"):
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

    for projectname in stage.list_projectnames_perstage():
        version = stage.get_latest_version_perstage(projectname)
        verdata = stage.get_versiondata_perstage(projectname, version)
        try:
            name, ver = verdata["name"], verdata["version"]
        except KeyError:
            log.error("metadata for project %r empty: %s, skipping",
                      projectname, verdata)
            continue
        show_toxresults = not (stage.user.name == 'root' and stage.index == 'pypi')
        linkstore = stage.get_linkstore_perstage(name, ver)
        packages.append(dict(
            info=dict(
                title="%s-%s" % (name, ver),
                url=request.route_url(
                    "/{user}/{index}/{name}/{version}",
                    user=stage.user.name, index=stage.index,
                    name=name, version=ver)),
            make_toxresults_url=functools.partial(
                request.route_url, "toxresults",
                user=stage.user.name, index=stage.index,
                name=name, version=ver),
            files=get_files_info(request, linkstore, show_toxresults),
            docs=get_docs_info(request, stage, verdata)))
    packages.sort(key=lambda x: x["info"]["title"])

    return result


@view_config(
    route_name="/{user}/{index}/{name}",
    accept="text/html", request_method="GET",
    renderer="templates/project.pt")
def project_get(context, request):
    context = ContextWrapper(context)
    try:
        releaselinks = context.stage.get_releaselinks(context.name)
    except context.stage.UpstreamError as e:
        log.error(e.msg)
        raise HTTPBadGateway(e.msg)
    if not releaselinks:
        raise HTTPNotFound("The project %s does not exist." % context.name)
    versions = []
    seen = set()
    for release in releaselinks:
        user, index = release.entrypath.split("/", 2)[:2]
        name, version = splitbasename(release)[:2]
        seen_key = (user, index, name, version)
        if seen_key in seen:
            continue
        versions.append(dict(
            index_title="%s/%s" % (user, index),
            index_url=request.stage_url(user, index),
            title=version,
            url=request.route_url(
                "/{user}/{index}/{name}/{version}",
                user=user, index=index, name=name, version=version)))
        seen.add(seen_key)
    return dict(
        title="%s/: %s versions" % (context.stage.name, name),
        versions=versions)


@view_config(
    route_name="/{user}/{index}/{name}/{version}",
    accept="text/html", request_method="GET",
    renderer="templates/version.pt")
def version_get(context, request):
    context = ContextWrapper(context)
    user, index = context.username, context.index
    name, version = context.name, context.version
    stage = context.stage
    try:
        verdata = context.verdata
    except stage.UpstreamError as e:
        log.error(e.msg)
        raise HTTPBadGateway(e.msg)
    infos = []
    skipped_keys = frozenset(
        ("description", "home_page", "name", "summary", "version"))
    for key, value in sorted(verdata.items()):
        if key in skipped_keys or key.startswith('+'):
            continue
        if isinstance(value, list):
            if not len(value):
                continue
            value = html.ul([html.li(x) for x in value]).unicode()
        else:
            if not value:
                continue
            value = py.xml.escape(value)
        infos.append((py.xml.escape(key), value))
    show_toxresults = not (user == 'root' and index == 'pypi')
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
            "/{user}/{index}/+simple/{name}",
            user=context.username, index=context.index, name=context.name)))
    return dict(
        title="%s/: %s-%s metadata and description" % (stage.name, name, version),
        content=get_description(stage, name, version),
        summary=verdata.get("summary"),
        nav_links=nav_links,
        infos=infos,
        files=files,
        show_toxresults=show_toxresults,
        make_toxresults_url=functools.partial(
            request.route_url, "toxresults",
            user=context.username, index=context.index,
            name=context.name, version=context.version),
        make_toxresult_url=functools.partial(
            request.route_url, "toxresult",
            user=context.username, index=context.index,
            name=context.name, version=context.version))


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
            context.stage.name, context.name, context.version),
        toxresults=toxresults,
        make_toxresult_url=functools.partial(
            request.route_url, "toxresult",
            user=context.username, index=context.index,
            name=context.name, version=context.version, basename=basename))


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
            context.stage.name, context.name, context.version, toxresult),
        toxresults=toxresults)


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
                entry = docs[sub_data['text_path']]
                text = entry['text']
                highlight = search_index.highlight(text, sub_hit.get('words'))
                title = sub_data.get('text_title', title)
                text_path = sub_data.get('text_path')
                if text_path:
                    sub_hit['url'] = self.request.route_url(
                        "docviewroot", user=data['user'], index=data['index'],
                        name=data['name'], version=data['doc_version'],
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
                        "/{user}/{index}/{name}/{version}",
                        user=data['user'], index=data['index'],
                        name=data['name'], version=data['version'],
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
                    "/{user}/{index}/{name}/{version}",
                    user=data['user'], index=data['index'],
                    name=data['name'], version=data['version'])
                item['title'] = "%s-%s" % (data['name'], data['version'])
            else:
                item['url'] = self.request.route_url(
                    "/{user}/{index}/{name}",
                    user=data['user'], index=data['index'], name=data['name'])
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
