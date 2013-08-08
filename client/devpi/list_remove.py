
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
            query_file_status(hub, origin)

def query_file_status(hub, origin):
    # XXX this code is not auto-tested in all detail
    # so change with great care or write tests first
    rooturl = hub.current.rooturl
    res = hub.http_api("get", urlutil.joinpath(rooturl, "/" + origin),
                       quiet=True)
    assert res.status_code == 200
    md5 = res["result"]["md5"]
    res = hub.http_api("get", urlutil.joinpath(rooturl,
                                               "/+tests/%s/toxresult" % md5),
                       quiet=True)
    assert res.status_code == 200
    assert res["type"] == "list:toxresult"
    seen = set()
    for toxresult in reversed(res["result"]):
        platform = toxresult["platform"]
        for envname, env in toxresult["testenvs"].items():
            prefix = "  {host} {platform} {envname}".format(
                     envname=envname, **toxresult)
            if prefix in seen:
                continue
            seen.add(prefix)
            setup = env.get("setup")
            if not setup:
                hub.error("%s no setup was performed" % prefix)
            elif has_failing_commands(setup):
                hub.error("%s setup failed" % prefix)
                show_commands(hub, setup)
            try:
                pyversion = env["python"]["version"].split(None, 1)[0]
            except KeyError:
                pass
            else:
                prefix = prefix + " " + pyversion
            test = env.get("test")
            if not test:
                hub.error("%s no tests were run" % prefix)
            elif has_failing_commands(test):
                hub.error("%s tests failed" % prefix)
                show_commands(hub, test)
            else:
                hub.line("%s tests passed" % prefix)

def has_failing_commands(commands):
    for command in commands:
        if command["retcode"] != "0":
            return True
    return False

def show_commands(hub, commands):
    if not hub.args.failures:
        return
    for command in commands:
        argv = command["command"]
        output = command["output"]
        shellcommand = " ".join(argv)
        if command["retcode"] != "0":
            hub.error("    FAIL: %s" % shellcommand)
            for line in output.split("\n"):
                hub.error("    %s" % line)
            break
        hub.info("    OK:  %s" % shellcommand)

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
    url = hub.current.get_project_url(name)
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
        url = current.get_index_url()
    else:
        url = urlutil.joinpath(current.get_index_url(), path) + "/"
    return hub.http_api("get", url, quiet=True)

def check_verify_current(hub):
    if not hub.current.index:
        hub.fatal("cannot use relative path without an active index")
