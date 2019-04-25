from __future__ import unicode_literals
from devpi_common.types import ensure_unicode
from devpi_common.metadata import get_sorted_versions
from devpi_common.validation import normalize_name
from devpi_server.log import threadlog as log
from devpi_web.doczip import Docs
import time


def is_project_cached(stage, project):
    if stage.ixconfig['type'] == 'mirror':
        if not stage.is_project_cached(project):
            return False
    return True


def preprocess_project(stage, name_input):
    name = normalize_name(name_input)
    try:
        user = stage.user.name
        index = stage.index
    except AttributeError:
        user, index = stage.name.split('/')
    user = ensure_unicode(user)
    index = ensure_unicode(index)
    if not is_project_cached(stage, name):
        return dict(name=name, user=user, index=index)
    setuptools_metadata = frozenset((
        'author', 'author_email', 'classifiers', 'description', 'download_url',
        'home_page', 'keywords', 'license', 'platform', 'summary'))
    versions = get_sorted_versions(stage.list_versions_perstage(name))
    result = dict(name=name)
    for i, version in enumerate(versions):
        if i == 0:
            verdata = stage.get_versiondata_perstage(name, version)
            result.update(verdata)
        links = stage.get_linkstore_perstage(name, version).get_links(rel="doczip")
        if links:
            result['doc_version'] = version
            result['+doczip'] = Docs(stage, name, version)
            break
        else:
            assert '+doczip' not in result

    result[u'user'] = user
    result[u'index'] = index
    for key in setuptools_metadata:
        if key in result:
            value = result[key]
            if value == 'UNKNOWN' or not value:
                del result[key]
    return result


def iter_projects(xom):
    timestamp = time.time()
    for user in xom.model.get_userlist():
        username = ensure_unicode(user.name)
        user_info = user.get(user)
        for index, index_info in user_info.get('indexes', {}).items():
            index = ensure_unicode(index)
            stage = xom.model.getstage(username, index)
            if stage is None:  # this is async, so the stage may be gone
                continue
            log.info("Search-Indexing %s:", stage.name)
            names = stage.list_projects_perstage()
            for count, name in enumerate(names, start=1):
                name = ensure_unicode(name)
                current_time = time.time()
                if current_time - timestamp > 3:
                    log.debug("currently search-indexed %s", count)
                    timestamp = current_time
                yield preprocess_project(stage, name)
