# coding: utf-8
from __future__ import unicode_literals
from devpi_common.metadata import get_pyversion_filetype, splitbasename
from devpi_common.types import ensure_unicode
from devpi_common.url import URL
from devpi_server.views import matchdict_parameters
from devpi_web.doczip import Docs, get_unpack_path
from operator import itemgetter
from py.xml import html
from pyramid.compat import decode_path_info
from pyramid.decorator import reify
from pyramid.httpexceptions import HTTPFound, HTTPNotFound
from pyramid.interfaces import IRoutesMapper
from pyramid.response import FileResponse
from pyramid.view import notfound_view_config, view_config
import logging
import py


log = logging.getLogger(__name__)


@view_config(route_name="docroot", request_method="GET")
@matchdict_parameters
def doc_serve(request, user, index, name, version, relpath):
    """ Serves the raw documentation files. """
    if not relpath:
        raise HTTPFound(location="index.html")
    xom = request.registry['xom']
    stage = xom.model.getstage(user, index)
    if not stage:
        raise HTTPNotFound("The stage %s/%s could not be found." % (user, index))
    doc_path = get_unpack_path(stage, name, version)
    if not doc_path.check():
        raise HTTPNotFound("No documentation available.")
    if not doc_path.join(relpath).check():
        raise HTTPNotFound("File %s not found in documentation." % relpath)
    return FileResponse(str(doc_path.join(relpath)))


@view_config(
    route_name="docviewroot",
    request_method="GET",
    renderer="templates/doc.pt")
@matchdict_parameters
def doc_show(request, user, index, name, version, relpath):
    """ Shows the documentation wrapped in an iframe """
    if not relpath:
        raise HTTPFound(location="index.html")
    xom = request.registry['xom']
    stage = xom.model.getstage(user, index)
    if not stage:
        raise HTTPNotFound("The stage %s/%s could not be found." % (user, index))
    doc_path = get_unpack_path(stage, name, version)
    if not doc_path.check():
        raise HTTPNotFound("No documentation available.")
    if not doc_path.join(relpath).check():
        raise HTTPNotFound("File %s not found in documentation." % relpath)
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


@notfound_view_config(
    request_method="GET", renderer="templates/notfound.pt")
def notfound(request):
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


def get_files_info(request, user, index, metadata):
    xom = request.registry['xom']
    files = []
    filedata = metadata.get("+files", {})
    if not filedata:
        log.warn(
            "project %r version %r has no files",
            metadata["name"], metadata.get("version"))
    for basename in sorted(filedata):
        entry = xom.filestore.get_file_entry(filedata[basename])
        relurl = URL(request.path).relpath("/" + entry.relpath)
        if entry.eggfragment:
            relurl += "#egg=%s" % entry.eggfragment
        elif entry.md5:
            relurl += "#md5=%s" % entry.md5
        py_version, file_type = get_pyversion_filetype(entry.basename)
        if py_version == 'source':
            py_version = ''
        size = ''
        if entry.file_exists():
            size = "%.0f %s" % sizeof_fmt(entry.file_size())
        files.append(dict(
            title=basename,
            url=request.relative_url(relurl),
            md5=entry.md5,
            dist_type=dist_file_types.get(file_type, ''),
            py_version=py_version,
            size=size))
    return files


def get_docs_info(request, stage, metadata):
    if stage.name == 'root/pypi':
        return
    name, ver = metadata["name"], metadata["version"]
    doc_path = get_unpack_path(stage, name, ver)
    if doc_path.exists():
        return dict(
            title="%s-%s docs" % (name, ver),
            url=request.route_url(
                "docviewroot", user=stage.user.name, index=stage.index,
                name=name, version=ver, relpath="index.html"))


@view_config(
    route_name='root',
    renderer='templates/root.pt')
def root(request):
    xom = request.registry['xom']
    rawusers = sorted(
        (x.get() for x in xom.model.get_userlist()),
        key=itemgetter('username'))
    users = []
    for user in rawusers:
        username = user['username']
        indexes = []
        for index in sorted(user.get('indexes', [])):
            indexes.append(dict(
                title="%s/%s" % (username, index),
                url=request.route_url(
                    "/{user}/{index}", user=username, index=index)))
        users.append(dict(
            title=username,
            indexes=indexes))
    return dict(users=users)


@view_config(
    route_name="/{user}/{index}", accept="text/html", request_method="GET",
    renderer="templates/index.pt")
@matchdict_parameters
def index_get(request, user, index):
    xom = request.registry['xom']
    stage = xom.model.getstage(user, index)
    if not stage:
        raise HTTPNotFound("The stage %s/%s could not be found." % (user, index))
    bases = []
    packages = []
    result = dict(
        title="%s index" % stage.name,
        simple_index_url=request.route_url(
            "/{user}/{index}/+simple/", user=user, index=index),
        bases=bases,
        packages=packages)
    if stage.name == "root/pypi":
        return result

    if hasattr(stage, "ixconfig"):
        for base in stage.ixconfig["bases"]:
            base_user, base_index = base.split('/')
            bases.append(dict(
                title=base,
                url=request.route_url(
                    "/{user}/{index}",
                    user=base_user, index=base_index),
                simple_url=request.route_url(
                    "/{user}/{index}/+simple/",
                    user=base_user, index=base_index)))

    for projectname in stage.getprojectnames_perstage():
        metadata = stage.get_metadata_latest_perstage(projectname)
        try:
            name, ver = metadata["name"], metadata["version"]
        except KeyError:
            log.error("metadata for project %r empty: %s, skipping",
                      projectname, metadata)
            continue
        packages.append(dict(
            info=dict(
                title="%s-%s info page" % (name, ver),
                url=request.route_url(
                    "/{user}/{index}/{name}/{version}",
                    user=stage.user.name, index=stage.index,
                    name=name, version=ver)),
            files=get_files_info(request, stage.user.name, stage.index, metadata),
            docs=get_docs_info(request, stage, metadata)))

    return result


@view_config(
    route_name="/{user}/{index}/{name}",
    accept="text/html", request_method="GET",
    renderer="templates/project.pt")
@matchdict_parameters
def project_get(request, user, index, name):
    xom = request.registry['xom']
    stage = xom.model.getstage(user, index)
    if not stage:
        raise HTTPNotFound("The stage %s/%s could not be found." % (user, index))
    name = ensure_unicode(name)
    releases = stage.getreleaselinks(name)
    if not releases:
        raise HTTPNotFound("The project %s does not exist." % name)
    versions = []
    seen = set()
    for release in releases:
        name, version = splitbasename(release)[:2]
        if version in seen:
            continue
        versions.append(dict(
            title=version,
            url=request.route_url(
                "/{user}/{index}/{name}/{version}",
                user=user, index=index, name=name, version=version)))
        seen.add(version)
    return dict(
        title="%s/: %s versions" % (stage.name, name),
        versions=versions)


@view_config(
    route_name="/{user}/{index}/{name}/{version}",
    accept="text/html", request_method="GET",
    renderer="templates/version.pt")
@matchdict_parameters
def version_get(request, user, index, name, version):
    xom = request.registry['xom']
    stage = xom.model.getstage(user, index)
    if not stage:
        raise HTTPNotFound("The stage %s/%s could not be found." % (user, index))
    name = ensure_unicode(name)
    version = ensure_unicode(version)
    metadata = stage.get_projectconfig(name)
    if not metadata:
        raise HTTPNotFound("The project %s does not exist." % name)
    verdata = metadata.get(version, None)
    if not verdata:
        raise HTTPNotFound("The version %s of project %s does not exist." % (version, name))
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
    return dict(
        title="%s/: %s-%s metadata and description" % (stage.name, name, version),
        content=stage.get_description(name, version),
        home_page=verdata.get("home_page"),
        summary=verdata.get("summary"),
        infos=infos,
        files=get_files_info(request, user, index, verdata),
        docs=get_docs_info(request, stage, verdata))


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
        self._projectinfo = {}
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

    def get_projectinfo(self, path):
        if path not in self._projectinfo:
            xom = self.request.registry['xom']
            user, index, name = path[1:].split('/')
            stage = xom.model.getstage(user, index)
            _load_project_cache = getattr(stage, '_load_project_cache', None)
            if _load_project_cache is None or _load_project_cache(name):
                projectconfig = stage.get_projectconfig(name)
            else:
                projectconfig = {}
            self._projectinfo['path'] = (stage, projectconfig)
        return self._projectinfo['path']

    def get_docs(self, stage, data):
        path = data['path']
        if path not in self._docs:
            self._docs[path] = Docs(stage, data['name'], data['doc_version'])
        return self._docs[path]

    def process_sub_hits(self, sub_hits, data):
        search_index = self.request.registry['search_index']
        stage, projectconfig = self.get_projectinfo(data['path'])
        result = []
        for sub_hit in sub_hits:
            sub_data = sub_hit['data']
            text_type = sub_data['type']
            if 'version' in data:
                metadata = projectconfig[data['version']]
            else:
                metadata = {}
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
                text = metadata.get(text_type)
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
        for item in result['items']:
            data = item['data']
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
            item['sub_hits'] = self.process_sub_hits(item['sub_hits'], data)
            more_results = result['info']['collapsed_counts'][data['path']]
            if more_results:
                new_params = dict(self.params)
                new_params['query'] = "%s path:%s" % (self.params['query'], data['path'])
                item['more_url'] = self.request.route_url(
                    'search',
                    _query=new_params)
                item['more_count'] = more_results
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
