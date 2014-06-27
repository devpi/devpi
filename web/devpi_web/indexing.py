from devpi_common.metadata import Version
from devpi_common.types import ensure_unicode
from devpi_server.log import threadlog as log
from devpi_web.doczip import iter_doc_contents
import time


def preprocess_project(stage, name, pconfig):
    try:
        user = stage.user.name
        index = stage.index
    except AttributeError:
        user, index = stage.name.split('/')
    setuptools_metadata = frozenset((
        'author', 'author_email', 'classifiers', 'description', 'download_url',
        'home_page', 'keywords', 'license', 'platform', 'summary'))
    versions = [x.string for x in sorted(map(Version, pconfig), reverse=True)]
    result = dict(name=name)
    for i, version in enumerate(versions):
        data = pconfig[version]
        if not i:
            result.update(data)
        pv = stage.get_project_version(name, version, projectconfig=pconfig)
        links = pv.get_links(rel="doczip")
        if links:
            # we assume it has been unpacked
            result['doc_version'] = version
            result['+doczip'] = iter_doc_contents(stage, name, version)
            break

    result[u'user'] = user
    result[u'index'] = index
    for key in setuptools_metadata:
        if key in result:
            value = result[key]
            if value == 'UNKNOWN' or not value:
                del result[key]
    return result


def get_projectconfig_without_fetch(stage, name):
    # we want to get the projectconfig we got without triggering a remote
    # fetch for root/pypi
    projectconfig = {}
    if stage.ixconfig['type'] == 'mirror':
        if stage._load_project_cache(name):
            projectconfig = stage.get_projectconfig(name)
    else:
        projectconfig = stage.get_projectconfig(name)
    return projectconfig


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
            names = stage.getprojectnames_perstage()
            for count, name in enumerate(names, start=1):
                name = ensure_unicode(name)
                current_time = time.time()
                if current_time - timestamp > 3:
                    log.debug("currently indexed %s", count)
                    timestamp = current_time
                if not stage.get_project_info(name):
                    continue
                metadata = get_projectconfig_without_fetch(stage, name)
                if metadata:
                    yield preprocess_project(stage, name, metadata)
                else:
                    yield dict(name=name, user=username, index=index)
