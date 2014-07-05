import json
from devpi_common.url import URL
from devpi_common.metadata import get_sorted_versions, parse_requirement
from devpi_common.viewhelp import ViewLinkStore

def out_index(hub, projects):
    for name in sorted(projects):
        out = name
        if hub.args.verbose:
            url = hub.current.get_project_url(name)
            reply = hub.http_api("get", url, type="projectconfig")
            maxversion = max(map(Version, reply.result))
            out += "-" + str(maxversion)
        hub.info(out)

def out_project(hub, reply, req):
    data = reply.result
    index = hub.current.index[len(hub.current.rooturl):]
    num = 0
    maxshow = 2
    for version in get_sorted_versions(data):
        if version not in req:
            continue
        if num > maxshow and not hub.args.all:
            num += 1
            continue
        verdata = data[version]
        if out_project_version_files(hub, reply.url, verdata, version, index):
            num += 1
        shadowing = data[version].get("+shadowing", [])
        for verdata in shadowing:
            if out_project_version_files(hub, reply.url, verdata, version, None):
                num += 1
    if not hub.args.all and num > (maxshow+1):
        hub.info("%s older versions not shown, use --all to see" %
                 (num-maxshow-1))


def out_project_version_files(hub, url, verdata, version, index):
    vv = ViewLinkStore(url, verdata)
    release_links = vv.get_links(rel="releasefile")
    for link in release_links:
        if version.startswith("egg="):
            origin = "%s (%s) " % (link.href, version)
        else:
            origin = link.href
        if index is None:
            hub.error(origin)
        elif origin.startswith(hub.current.index):
            hub.info(origin)
        else:
            hub.line(origin)
        toxlinks = vv.get_links(rel="toxresult", for_href=link.href)
        if toxlinks:
            show_test_status(hub, toxlinks)
    return bool(release_links)

def show_test_status(hub, toxlinks):
    # XXX this code is not auto-tested in all detail
    # so change with great care or write tests first
    seen = set()
    for toxlink in toxlinks:
        res = hub.http.get(toxlink.href)
        assert res.status_code == 200
        toxresult = json.loads(res.content.decode("utf8"))
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
        out_project(hub, reply, req)
    else:
        reply = hub.http_api("get", hub.current.index, type="indexconfig")
        out_index(hub, reply.result["projects"])

def main_remove(hub, args):
    hub.require_valid_current_with_index()
    args = hub.args
    req = parse_requirement(args.spec)
    url = hub.current.get_project_url(req.project_name)
    reply = hub.http_api("get", url, type="projectconfig")
    ver_to_delete = confirm_delete(hub, reply, req)
    if not ver_to_delete:
        hub.error("not deleting anything")
        return 1
    else:
        for ver, links in ver_to_delete:
            hub.info("deleting release %s of %s" % (ver, req.project_name))
            hub.http_api("delete", url.addpath(ver))

def confirm_delete(hub, reply, req):
    basepath = URL(hub.current.index).path.lstrip("/")
    ver_to_delete = []
    for version, verdata in reply.result.items():
        if version in req:
            vv = ViewLinkStore(basepath, verdata)
            files_to_delete = [link for link in vv.get_links()
                                if link.href.startswith(hub.current.index)]
            if files_to_delete:  # XXX need to delete metadata without files
                ver_to_delete.append((version, files_to_delete))
    if ver_to_delete:
        hub.info("About to remove the following releases and distributions")
        for ver, links in ver_to_delete:
            hub.info("version: " + ver)
            for link in links:
                hub.info("  - " + link.href)
        if hub.ask_confirm("Are you sure"):
            return ver_to_delete

#def filter_versions(spec, lines):
    #    ver = pkg_resources.parse_version(line)
#    req = pkg_resources.Requirement.parse(spec)
#    if ver in req:
#        pass

def check_verify_current(hub):
    if not hub.current.index:
        hub.fatal("cannot use relative path without an active index")
