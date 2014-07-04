from devpi_common.types import ensure_unicode
from devpi_common.metadata import get_sorted_versions
from devpi_server.log import threadlog as log
from devpi_web.doczip import iter_doc_contents
import time


def is_project_cached(stage, name):
    if stage.ixconfig['type'] == 'mirror':
        if not stage._load_project_cache(name):
            return False
    return True


def preprocess_project(stage, name):
    try:
        user = stage.user.name
        index = stage.index
    except AttributeError:
        user, index = stage.name.split('/')
    if not is_project_cached(stage, name):
        return dict(name=name, user=user, index=index)
    setuptools_metadata = frozenset((
        'author', 'author_email', 'classifiers', 'description', 'download_url',
        'home_page', 'keywords', 'license', 'platform', 'summary'))
    versions = get_sorted_versions(stage.list_versions(name))
    result = dict(name=name)
    for i, version in enumerate(versions):
        verdata = stage.get_versiondata(name, version)
        if not i:
            result.update(verdata)
        pv = stage.get_versionlinks(name, version)
        links = pv.get_links(rel="doczip")
        if links:
            # we assume it has been unpacked
            result['doc_version'] = version
            result['+doczip'] = iter_doc_contents(stage, name, version)
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
            stage = xom.model.getstage('%s/%s' % (username, index))
            if stage is None:  # this is async, so the stage may be gone
                continue
            log.info("Indexing %s/%s:" % (username, index))
            names = stage.list_projectnames_perstage()
            for count, name in enumerate(names, start=1):
                name = ensure_unicode(name)
                current_time = time.time()
                if current_time - timestamp > 3:
                    log.debug("currently indexed %s", count)
                    timestamp = current_time
                if stage.get_projectname(name) is None:
                    continue
                yield preprocess_project(stage, name)
