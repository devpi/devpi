
import os
import py
import pkg_resources

from devpi.util import version as verutil
from devpi.util import url as urlutil
from pkg_resources import parse_version

from devpi import log
import posixpath

def out_index(hub, data):
    for name in sorted(data):
        hub.info(name)

def out_project(hub, data, name):
    versions = list(data)
    def cmpversion(x, y):
        return cmp(parse_version(x), parse_version(y))

    index = hub.current.index[len(hub.current.rooturl):]

    versions.sort(cmp=cmpversion)
    for version in reversed(versions):
        #hub.info("%s-%s:" % (name, version))
        verdata = data[version]
        out_project_version_files(hub, verdata, version, index)
        shadowing = data[version].get("+shadowing", [])
        for verdata in shadowing:
            out_project_version_files(hub, verdata, version, None)

def out_project_version_files(hub, verdata, version, index):
    files = verdata.get("+files")
    if files is not None:
        for fn in files:
            origin = files[fn]
            if version.startswith("egg="):
                origin = "%s (%s) " % (origin, version)
            if index is None:
                hub.error(origin)
            elif origin.startswith(index):
                hub.info(origin)
            else:
                hub.line(origin)

def main_list(hub, args):
    current = hub.current
    args = hub.args

    if not args.spec:
        data = getjson(hub, None)
        out_index(hub, data["result"])
    else:
        data = getjson(hub, args.spec)
        out_project(hub, data["result"], args.spec)

def main_remove(hub, args):
    current = hub.current
    args = hub.args

    name, ver, suffix = verutil.splitbasename(args.spec)
    if suffix:
        hub.fatal("can only delete releases, not single release files")
    url = hub.get_project_url(name)
    if ver:
        url = url + ver + "/"
    data = hub.http_api("get", url)
    if confirm_delete(hub, data):
        hub.http_api("delete", url)

def confirm_delete(hub, data):
    basepath = urlutil.getpath(hub.current.index).lstrip("/")
    to_delete = []
    if data["type"] == "projectconfig":
        for version, verdata in data["result"].items():
            to_delete.extend(match_release_files(basepath, verdata))
    elif data["type"] == "versiondata":
        to_delete.extend(match_release_files(basepath, data["result"]))
    if not to_delete:
        hub.line("nothing to delete")
        return None
    else:
        hub.info("About to remove the following release files and metadata:")
        for fil in to_delete:
            hub.info("   " + fil)
        return hub.ask_confirm("Are you sure")

def match_release_files(basepath, verdata):
    files = verdata.get("+files", {})
    for fil in files.values():
        if fil.startswith(basepath):
            yield fil

#def filter_versions(spec, lines):
    #    ver = pkg_resources.parse_version(line)
#    req = pkg_resources.Requirement.parse(spec)
#    if ver in req:
#        pass

def getjson(hub, path):
    current = hub.current
    if not path:
        check_verify_current(hub)
        url = hub.get_index_url()
    else:
        url = urlutil.joinpath(hub.get_index_url(), path) + "/"
    return hub.http_api("get", url, quiet=True)

def check_verify_current(hub):
    if not hub.current.index:
        hub.fatal("cannot use relative path without an active index")
