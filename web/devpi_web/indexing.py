from devpi_common.metadata import Version
from devpi_common.types import ensure_unicode
from devpi_web.doczip import iter_doc_contents
from logging import getLogger
import py
import time


log = getLogger(__name__)


def preprocess_project(stage, name, info):
    try:
        user = stage.user.name
        index = stage.index
    except AttributeError:
        user, index = stage.name.split('/')
    setuptools_metadata = frozenset((
        'author', 'author_email', 'classifiers', 'description', 'download_url',
        'home_page', 'keywords', 'license', 'platform', 'summary'))
    versions = [x.string for x in sorted(map(Version, info), reverse=True)]
    result = dict(name=name)
    for i, version in enumerate(versions):
        data = info[version]
        if not i:
            result.update(data)
        if "+doczip" in data:
            result['+doczip'] = data['+doczip']
            result['doc_version'] = version
            break
    result[u'user'] = user
    result[u'index'] = index
    for key in setuptools_metadata:
        if key in result:
            value = result[key]
            if value == 'UNKNOWN' or not value:
                del result[key]
    if '+doczip' in result:
        result['+doczip'] = iter_doc_contents(stage, name, result['doc_version'])
    return result


def iter_projects(xom):
    tw = py.io.TerminalWriter()
    timestamp = time.time()
    for user in xom.model.get_userlist():
        username = ensure_unicode(user.name)
        user_info = user.get(user)
        for index, index_info in user_info.get('indexes', {}).items():
            index = ensure_unicode(index)
            stage = xom.model.getstage('%s/%s' % (username, index))
            # if stage is None:
            #     continue
            _load_project_cache = getattr(
                stage, '_load_project_cache', None)
            log.info("Indexing %s/%s:" % (username, index))
            names = stage.getprojectnames_perstage()
            length = len(names)
            for count, name in enumerate(names, start=1):
                name = ensure_unicode(name)
                current_time = time.time()
                if current_time - timestamp > 1:
                    timestamp = current_time
                    tw.write("%7d/%d\r" % (count, length))
                if not stage.get_project_info(name):
                    continue
                metadata = None
                if _load_project_cache is None or _load_project_cache(name):
                    metadata = stage.get_projectconfig(name)
                if metadata:
                    yield preprocess_project(stage, name, metadata)
                else:
                    yield dict(name=name, user=username, index=index)
            tw.line()
