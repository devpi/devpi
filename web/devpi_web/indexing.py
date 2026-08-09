from __future__ import annotations

from attrs import define
from collections.abc import Mapping
from devpi_common.metadata import get_sorted_versions
from devpi_common.types import ensure_unicode
from devpi_common.validation import normalize_name
from devpi_server.log import threadlog as log
from devpi_web.config import get_pluginmanager
from devpi_web.doczip import Docs
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from typing import Any


def is_project_cached(stage, project):
    return not (
        stage.ixconfig["type"] in {"mirror", "remote"}
        and not stage.is_project_cached(project)
    )


def preprocess_project(project: ProjectIndexingInfo) -> dict | None:
    stage = project.stage
    pm = get_pluginmanager(stage.xom.config)
    name = normalize_name(project.name)
    try:
        user = stage.user.name
        index = stage.index
    except AttributeError:
        user, index = stage.name.split('/')
    user = ensure_unicode(user)
    index = ensure_unicode(index)
    result: dict[str, object]
    if project.is_from_mirror:
        stage.offline = True
        if not stage.is_project_cached(name):
            # only index basic info for projects with no downloads
            result = dict(name=project.name, user=user, index=index)
            pm.hook.devpiweb_modify_preprocess_project_result(
                project=project, result=result
            )
            return result
    elif not stage.has_project_perstage(name):
        # project doesn't exist anymore
        return None
    # metadata_keys is only available on private indexes
    setuptools_metadata = frozenset(getattr(stage, 'metadata_keys', ()))
    versions = get_sorted_versions(stage.list_versions_perstage(name))
    result = dict(name=project.name)
    for i, version in enumerate(versions):
        if i == 0:
            verdata = stage.get_versiondata_perstage(project.name, version)
            result.update(verdata)
        if project.is_from_mirror:
            break
        links = stage.get_linkstore_perstage(name, version).get_links(rel="doczip")
        if links:
            docs = Docs(stage, project.name, version)
            if docs.exists():
                result['doc_version'] = version
                result['+doczip'] = docs
            break
        assert "+doczip" not in result

    result[u'user'] = user
    result[u'index'] = index
    for key in setuptools_metadata:
        if key in result:
            value = result[key]
            if value == 'UNKNOWN' or not value:
                del result[key]
    pm.hook.devpiweb_modify_preprocess_project_result(
        project=project, result=result)
    return result


@define
class ProjectIndexingInfo:
    stage: Any
    name: str
    num_names: int

    @property
    def indexname(self) -> str:
        return self.stage.name

    @property
    def is_from_mirror(self) -> bool:
        return self.stage.ixconfig["type"] in {"mirror", "remote"}


def iter_indexes(xom):
    mirrors = []
    for user in xom.model.get_userlist():
        username = ensure_unicode(user.name)
        user_info = user.get()
        for index, index_info in user_info.get('indexes', {}).items():
            index = ensure_unicode(index)
            if index_info["type"] in {"mirror", "remote"}:
                mirrors.append((username, index))
            else:
                yield (username, index)
    yield from mirrors


def iter_projects(xom, *, offline=True):
    for username, index in iter_indexes(xom):
        stage = xom.model.getstage(username, index)
        if stage is None:  # this is async, so the stage may be gone
            continue
        index_type = stage.ixconfig["type"]
        # only go offline after we got the projects list
        if index_type in {"mirror", "remote"}:
            stage.offline = offline
        if index_type == "remote" and not stage.ixconfig.get(
            "remote_include_in_search", False
        ):
            log.info(
                "skipping '%s' remote because 'remote_include_in_search' is False",
                stage.name,
            )
            return
        names = stage.list_projects_perstage()
        if isinstance(names, Mapping):
            # since devpi-server 6.6.0 mirrors return a mapping where
            # the un-normalized names are in the values
            names = names.values()
        num_names = len(names)
        for name in names:
            yield ProjectIndexingInfo(
                stage=stage, name=ensure_unicode(name), num_names=num_names
            )
