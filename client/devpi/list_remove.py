import json
from devpi_common.metadata import get_sorted_versions, parse_requirement, Version
from devpi_common.viewhelp import ViewLinkStore, iter_toxresults
from functools import partial


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
        show_toxresults = hub.args.toxresults or hub.args.failures
        if show_toxresults and toxlinks:
            show_test_status(hub, toxlinks)
    return bool(release_links)


def _load_toxresult(hub, link):
    res = hub.http.get(link.href)
    assert res.status_code == 200
    return json.loads(res.content.decode("utf8"))


def show_test_status(hub, toxlinks):
    load_toxresult = partial(_load_toxresult, hub)
    for toxlink, toxenvs in iter_toxresults(toxlinks, load_toxresult):
        if toxenvs is None:
            hub.error("corrupt toxresult, skipping: %s" % (toxlink,))
            continue
        for toxenv in toxenvs:
            prefix = "%-10s %-7s %-10s" % (toxenv.host, toxenv.platform, toxenv.envname)
            if not toxenv.setup['commands']:
                hub.error("%s no setup was performed" % prefix)
            elif toxenv.setup['failed']:
                hub.error("%s setup failed" % prefix)
                show_commands(hub, toxenv.setup)
            if toxenv.pyversion:
                prefix = prefix + " " + toxenv.pyversion
            if not toxenv.test['commands']:
                hub.error("%s no tests were run" % prefix)
            elif toxenv.test['failed']:
                hub.error("%s tests failed" % prefix)
                show_commands(hub, toxenv.test)
            else:
                hub.line("%s tests passed" % prefix)


def show_commands(hub, view_result):
    if not hub.args.failures:
        return
    for command_dict in view_result["commands"]:
        shellcommand = command_dict["command"]
        output = command_dict["output"]
        if command_dict["failed"]:
            hub.error("    FAIL: %s" % shellcommand)
            for line in output.split("\n"):
                hub.error("    %s" % line)
            break
        hub.info("    OK:  %s" % shellcommand)

def main_list(hub, args):
    hub.require_valid_current_with_index()
    if hub.args.spec:
        req = parse_requirement(hub.args.spec)
        url = hub.current.get_project_url(
            req.project_name, indexname=args.index)
        reply = hub.http_api("get", url, type="projectconfig")
        out_project(hub, reply, req)
    else:
        index = hub.current.index
        if args.index:
            if args.index.count("/") > 1:
                hub.fatal("index %r not of form USER/NAME or NAME" % args.index)
            index = hub.current.get_index_url(args.index, slash=False)
        reply = hub.http_api("get", index, type="indexconfig")
        out_index(hub, reply.result["projects"])


def main_remove(hub, args):
    hub.require_valid_current_with_index()
    args = hub.args
    spec_or_url = args.spec_or_url
    if spec_or_url.startswith(('http://', 'https://')):
        # delete specified file
        url = spec_or_url
        if confirm_delete_file(hub, url):
            hub.http_api("delete", url)
        return

    # else delete project, release or distribution
    req = parse_requirement(args.spec_or_url)
    if args.index and args.index.count("/") > 1:
        hub.fatal("index %r not of form USER/NAME or NAME" % args.index)
    index_url = hub.current.get_index_url(indexname=args.index)
    proj_url = hub.current.get_project_url(
        req.project_name, indexname=args.index)
    reply = hub.http_api("get", proj_url, type="projectconfig")
    ver_to_delete = get_versions_to_delete(index_url, reply, req)
    if not ver_to_delete:
        hub.error(
            "No releases or distributions found matching '%s'." % args.spec_or_url)
        return 1
    if confirm_delete(hub, ver_to_delete):
        if req.specs:
            # delete specific versions
            for ver, links in ver_to_delete:
                hub.info("deleting release %s of %s" % (ver, req.project_name))
                hub.http_api("delete", proj_url.addpath(ver))
        else:
            # delete whole project
            hub.http_api("delete", proj_url)
    else:
        hub.error("not deleting anything")


def confirm_delete_file(hub, url):
    hub.info("About to remove the following file:")
    hub.info(url)
    return hub.ask_confirm("Are you sure")


def get_versions_to_delete(index_url, response, requirement):
    basepath = index_url.path.lstrip("/")
    ver_to_delete = []
    for version, verdata in response.result.items():
        if version in requirement:
            vv = ViewLinkStore(basepath, verdata)
            files_to_delete = [link for link in vv.get_links()
                               if link.href.startswith(index_url.url)]
            ver_to_delete.append((version, files_to_delete))
    return ver_to_delete


def confirm_delete(hub, ver_to_delete):
    hub.info("About to remove the following releases and distributions")
    for ver, links in ver_to_delete:
        hub.info("version: " + ver)
        if links:
            for link in links:
                hub.info("  - " + link.href)
        else:
            hub.info("  - No releases")
    return hub.ask_confirm("Are you sure")
