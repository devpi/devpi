from __future__ import unicode_literals
import py
import sys
import subprocess
from collections import OrderedDict
from devpi_common.url import URL
from functools import partial
from plistlib import dumps as plist_dumps

from devpi_server.config import hookimpl
from devpi_server.config import parseoptions, get_parser, get_pluginmanager


# don't sort the keys; that way we can keep our own order
write_plist_to_bytes = partial(plist_dumps, sort_keys=False)


def render(confname, format=None, **kw):
    template = confname + ".template"
    from pkg_resources import resource_string
    templatestring = resource_string("devpi_server.cfg", template)
    if not py.builtin._istext(templatestring):
        templatestring = py.builtin._totext(templatestring, "utf-8")

    kw = dict((x[0], str(x[1])) for x in kw.items())
    if format is None:
        result = templatestring.format(**kw)
    else:
        result = templatestring % kw
    return result


def get_devpibin(tw):
    devpibin = py.path.local(
        sys.argv[0].replace("devpi-gen-config", "devpi-server"))
    if not devpibin.exists():
        tw.line(
            "The devpi-server executable doesn't exist in the following "
            "expected location:\n%s\nYou might have to edit the following "
            "config." % devpibin,
            yellow=True)
    return devpibin


def gen_supervisor(tw, config, argv, writer):
    import getpass
    devpibin = get_devpibin(tw)
    content = render(
        "supervisor-devpi.conf",
        server_args=subprocess.list2cmdline(argv),
        user=getpass.getuser(),
        devpibin=devpibin)
    writer("supervisor-devpi.conf", content)
    content = render("supervisord.conf")
    writer("supervisord.conf", content)


def gen_cron(tw, config, argv, writer):
    import getpass
    content = render(
        "crontab",
        user=getpass.getuser())
    writer("crontab", content)


def gen_nginx(tw, config, argv, writer):
    outside_url = config.args.outside_url
    if outside_url is None:  # default
        outside_url = "http://localhost:80"

    parts = URL(outside_url).netloc.split(":")
    if len(parts) < 2:
        parts.append(80)
    outside_host, outside_port = parts

    nginxconf = render("nginx-devpi.conf", format=1,
                       outside_url=outside_url,
                       outside_host=outside_host,
                       outside_port=outside_port,
                       port=config.args.port,
                       serverdir=config.serverdir)
    writer("nginx-devpi.conf", nginxconf)


def gen_launchd(tw, config, argv, writer):
    devpibin = get_devpibin(tw)
    plist_content = write_plist_to_bytes(OrderedDict([
        ("Label", "net.devpi"),
        ("ProgramArguments", [str(devpibin)] + argv),
        ("RunAtLoad", True),
    ]))
    writer("net.devpi.plist", plist_content)
    content = render("launchd-macos.txt")
    writer("launchd-macos.txt", content)


def gen_systemd(tw, config, argv, writer):
    import getpass
    devpibin = get_devpibin(tw)
    content = render(
        "devpi.service",
        server_args=subprocess.list2cmdline(argv),
        user=getpass.getuser(),
        devpibin=devpibin,
    )
    writer("devpi.service", content)


def gen_windows_service(tw, config, argv, writer):
    devpibin = get_devpibin(tw)
    content = render(
        "windows-service.txt",
        server_args=subprocess.list2cmdline(argv),
        devpibin=devpibin)
    writer("windows-service.txt", content)


@hookimpl
def devpiserver_genconfig(tw, config, argv, writer):
    gen_cron(tw, config, argv, writer)
    gen_launchd(tw, config, argv, writer)
    gen_nginx(tw, config, argv, writer)
    gen_supervisor(tw, config, argv, writer)
    gen_systemd(tw, config, argv, writer)
    gen_windows_service(tw, config, argv, writer)


def genconfig(config=None, argv=None):
    pluginmanager = get_pluginmanager()

    if argv is None:
        argv = sys.argv
        argv = [str(x) for x in argv]

    if config is None:
        parser = get_parser(pluginmanager)
        parser.description = (
            "Write configuration files for various process managers and "
            "webservers. Takes same arguments as devpi-server.")
        config = parseoptions(pluginmanager, argv, parser=parser)

    tw = py.io.TerminalWriter()
    tw.cwd = py.path.local()

    if not config.args.configfile:
        tw.line(
            "It is highly recommended to use a configuration file for "
            "devpi-server, see --configfile option.",
            red=True)

    destdir = tw.cwd.ensure("gen-config", dir=1)

    new_argv = []
    argv_iter = iter(argv[1:])
    for arg in argv_iter:
        if arg.startswith("--serverdir"):
            if '=' not in arg:
                next(argv_iter)  # remove path
            # replace with absolute path
            new_argv.extend([
                "--serverdir",
                config.serverdir.strpath])
            continue
        if arg == "-c" or arg.startswith(("--configfile", "-c=")):
            if '=' not in arg:
                next(argv_iter)  # remove path
            # replace with absolute path
            new_argv.extend([
                "--configfile",
                py.path.local(config.args.configfile).strpath])
            continue
        new_argv.append(arg)
    new_config = parseoptions(pluginmanager, ["devpi-server"] + new_argv)

    def writer(basename, content):
        p = destdir.join(basename)
        p.write(content)
        tw.line("wrote %s" % p.relto(tw.cwd), bold=True)

    config.hook.devpiserver_genconfig(
        tw=tw, config=new_config, argv=new_argv, writer=writer)
