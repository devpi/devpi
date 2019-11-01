from __future__ import unicode_literals
import py
import sys
import subprocess
from collections import OrderedDict
from devpi_common.url import URL

from devpi_server.config import (
    render, parseoptions, get_parser, get_pluginmanager
)

try:
    # python >= 3.4
    from plistlib import dumps as plist_dumps
    # don't sort the keys; that way we can keep our own order
    write_plist_to_bytes = lambda d: plist_dumps(d, sort_keys=False)
except ImportError:
    try:
        # python 3.0-3.3
        from plistlib import writePlistToBytes as write_plist_to_bytes
    except ImportError:
        # python 2
        from plistlib import writePlistToString as write_plist_to_bytes


def get_devpibin():
    return py.path.local(sys.argv[0].replace("devpi-gen-config", "devpi-server"))


def gen_supervisor(tw, config, argv, writer):
    import getpass
    devpibin = get_devpibin()
    assert devpibin.exists()
    content = render(
            tw, "supervisor-devpi.conf",
            server_args=subprocess.list2cmdline(argv),
            user=getpass.getuser(),
            devpibin=devpibin,
    )
    writer("supervisor-devpi.conf", content)
    content = render(
            tw, "supervisord.conf",
    )
    writer("supervisord.conf", content)


def gen_cron(tw, config, argv, writer):
    import getpass
    content = render(
        tw, "crontab",
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

    nginxconf = render(tw, "nginx-devpi.conf", format=1,
                       outside_url=outside_url,
                       outside_host=outside_host,
                       outside_port=outside_port,
                       port=config.args.port,
                       serverdir=config.serverdir)
    writer("nginx-devpi.conf", nginxconf)


def gen_launchd(tw, config, argv, writer):
    devpibin = get_devpibin()
    plist_content = write_plist_to_bytes(OrderedDict([
        ("Label", "net.devpi"),
        ("ProgramArguments", [str(devpibin)] + argv),
        ("RunAtLoad", True),
    ]))
    writer("net.devpi.plist", plist_content)
    content = render(
        tw, "launchd-macos.txt")
    writer("launchd-macos.txt", content)


def gen_systemd(tw, config, argv, writer):
    import getpass
    devpibin = get_devpibin()
    assert devpibin.exists()
    content = render(
        tw, "devpi.service",
        server_args=subprocess.list2cmdline(argv),
        user=getpass.getuser(),
        devpibin=devpibin,
    )
    writer("devpi.service", content)


def gen_windows_service(tw, config, argv, writer):
    devpibin = get_devpibin()
    assert devpibin.exists()
    content = render(
        tw, "windows-service.txt",
        server_args=subprocess.list2cmdline(argv),
        devpibin=devpibin)
    writer("windows-service.txt", content)


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
        if arg == "--gen-config":
            continue
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
    new_args = parseoptions(pluginmanager, ["devpi-server"] + new_argv)
    cfg_types = [
        "cron",
        "launchd",
        "nginx",
        "supervisor",
        "systemd",
        "windows_service"]
    for cfg_type in cfg_types:
        def writer(basename, content):
            p = destdir.join(basename)
            p.write(content)
            tw.line("wrote %s" % p.relto(tw.cwd), bold=True)
        name = "gen_" + cfg_type
        globals()[name](tw, new_args, new_argv, writer)
