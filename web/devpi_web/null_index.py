from devpi_web.indexing import is_project_cached
from operator import itemgetter
from pluggy import HookimplMarker
import re


hookimpl = HookimplMarker("devpiweb")


class Index:
    def __init__(self, config, settings):
        pass

    def delete_index(self):
        pass

    def delete_projects(self, projects):
        pass

    def update_projects(self, projects, clear=False):
        pass

    def query_projects(self, querystring, page=1):
        return dict(items=[])

    def _matcher(self, searchinfo):
        items = list(
            re.escape(x)
            for x in searchinfo['fields']['name'])
        return re.compile('|'.join(items)).search

    def query_packages(self, searchinfo, sro):
        hits = []
        matcher = self._matcher(searchinfo)
        found = set()
        for stage in sro:
            names = stage.list_projects_perstage()
            for name in names:
                if matcher(name) is None:
                    continue
                if name in found:
                    continue
                found.add(name)
                version = ''
                summary = '[%s]' % stage.name
                if is_project_cached(stage, name):
                    version = stage.get_latest_version(name)
                    metadata = stage.get_versiondata(name, version)
                    summary += ' %s' % metadata.get('summary', '')
                hits.append(dict(
                    name=name, summary=summary.strip(), version=version,
                    _pypi_ordering=0))
        return sorted(hits, key=itemgetter('name'))

    def get_query_parser_html_help(self):
        return [
            "No search available, because the 'Null' indexer backend is "
            "in use."]


@hookimpl
def devpiweb_indexer_backend():
    return dict(
        indexer=Index,
        name="null",
        description="Null indexer backend, only name based 'pip search' supported.")
