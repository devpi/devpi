
from devpi_common.url import URL
from devpi_common.metadata import splitbasename, Version

def out_index(hub, data):
    for name in sorted(data):
        hub.info(name)

def out_project(hub, data):
    index = hub.current.index[len(hub.current.rooturl):]
    num = 0
    for ver in sorted(map(Version, data), reverse=True):
        if num > 0 and not hub.args.all:
            num += 1
            continue
        version = ver.string
        #hub.info("%s-%s:" % (name, version))
        verdata = data[version]
        if out_project_version_files(hub, verdata, version, index):
            num += 1
        shadowing = data[version].get("+shadowing", [])
        for verdata in shadowing:
            if out_project_version_files(hub, verdata, version, None):
                num += 1
    if not hub.args.all and num > 1:
        hub.info("%s older versions not shown, use --all to see" % (num-1))

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
    url = get_url(hub, hub.args.spec)
    hub.info("list result: %s" % url.url)
    reply = hub.http_api("get", url, quiet=True)
    if reply.type == "list:projectconfig":
        out_index(hub, reply.result)
    elif reply.type == "projectconfig":
        out_project(hub, reply.result)
    else:
        hub.fatal("cannot show result type: %s "
                  "(use getjson to get raw data)" % (reply.type,))

def get_url(hub, target):
    if not target:
        check_verify_current(hub)
        url = hub.current.index_url
    else:
        url = hub.current.index_url.addpath(target, asdir=1)
    return url

def main_remove(hub, args):
    hub.require_valid_current_with_index()
    args = hub.args

    name, ver, suffix = splitbasename(args.spec, checkarch=False)
    if suffix:
        hub.fatal("can only delete releases, not single release files")
    url = hub.current.get_project_url(name)
    if ver:
        url = url + ver + "/"
    reply = hub.http_api("get", url)
    if confirm_delete(hub, reply):
        hub.http_api("delete", url)

def confirm_delete(hub, reply):
    basepath = URL(hub.current.index).path.lstrip("/")
    to_delete = []
    if reply.type == "projectconfig":
        for version, verdata in reply.result.items():
            to_delete.extend(match_release_files(basepath, verdata))
    elif reply.type == "versiondata":
        to_delete.extend(match_release_files(basepath, reply.result))
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

def check_verify_current(hub):
    if not hub.current.index:
        hub.fatal("cannot use relative path without an active index")
