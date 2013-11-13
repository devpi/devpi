
from devpi_common.url import URL
from devpi_common.metadata import Version, parse_requirement

def out_index(hub, data):
    for name in sorted(data):
        hub.info(name)

def out_project(hub, data, req):
    index = hub.current.index[len(hub.current.rooturl):]
    num = 0
    maxshow = 2
    for ver in sorted(map(Version, data), reverse=True):
        version = ver.string
        if version not in req:
            continue
        if num > maxshow and not hub.args.all:
            num += 1
            continue
        verdata = data[version]
        if out_project_version_files(hub, verdata, version, index):
            num += 1
        shadowing = data[version].get("+shadowing", [])
        for verdata in shadowing:
            if out_project_version_files(hub, verdata, version, None):
                num += 1
    if not hub.args.all and num > (maxshow+1):
        hub.info("%s older versions not shown, use --all to see" %
                 (num-maxshow-1))

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
    return bool(files)

def query_file_status(hub, origin):
    # XXX this code is not auto-tested in all detail
    # so change with great care or write tests first
    rooturl = hub.current.rooturl
    res = hub.http_api("get", URL(rooturl, "/" + origin).url,
                       quiet=True)
    assert res.status_code == 200
    md5 = res.result.get("md5")
    if not md5:
        return
    res = hub.http_api("get",
                       URL(rooturl, "/+tests/%s/toxresult" % md5).url,
                       quiet=True, type="list:toxresult")
    seen = set()
    for toxresult in reversed(res.result):
        toxresult["platform"]
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
    hub.require_valid_current_with_index()
    if hub.args.spec:
        req = parse_requirement(hub.args.spec)
        url = hub.current.get_project_url(req.project_name)
        reply = hub.http_api("get", url, type="projectconfig")
        out_project(hub, reply.result, req)
    else:
        reply = hub.http_api("get", hub.current.index,
                             type="list:projectconfig")
        out_index(hub, reply.result)

def main_remove(hub, args):
    hub.require_valid_current_with_index()
    args = hub.args
    req = parse_requirement(args.spec)
    url = hub.current.get_project_url(req.project_name)
    reply = hub.http_api("get", url, type="projectconfig")
    ver_to_delete = confirm_delete(hub, reply, req)
    if ver_to_delete is None:
        hub.error("not deleting anything")
        return 1
    else:
        for ver, files in ver_to_delete:
            hub.info("deleting release %s of %s" % (ver, req.project_name))
            hub.http_api("delete", url.addpath(ver))

def confirm_delete(hub, reply, req):
    basepath = URL(hub.current.index).path.lstrip("/")
    ver_to_delete = []
    for version, verdata in reply.result.items():
        if version in req:
            files_to_delete = list(match_release_files(basepath, verdata))
            if files_to_delete:  # XXX need to delete metadata without files
                ver_to_delete.append((version, files_to_delete))
    if ver_to_delete:
        hub.info("About to remove the following releases and distributions")
        for ver, files in ver_to_delete:
            hub.info("   version: " + ver)
            for fil in files:
                hub.info("   - " + fil)
        if hub.ask_confirm("Are you sure"):
            return ver_to_delete

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

def check_verify_current(hub):
    if not hub.current.index:
        hub.fatal("cannot use relative path without an active index")
