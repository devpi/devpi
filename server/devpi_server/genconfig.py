from __future__ import unicode_literals
import os
import py
import sys
import subprocess
from collections import OrderedDict
from devpi_common.url import URL

from devpi_server.config import (
    render, parseoptions, get_pluginmanager
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


def gen_supervisor(tw, config, argv, writer):
    import getpass
    devpibin = py.path.local(sys.argv[0])
    assert devpibin.exists()
    content = render(
            tw, "supervisord.conf",
            server_args=subprocess.list2cmdline(argv),
            user=getpass.getuser(),
            devpibin=devpibin,
    )
    writer("supervisor-devpi.conf", content)


def gen_cron(tw, config, argv, writer):
    devpibin = py.path.local(sys.argv[0])
    newcrontab = "@reboot %s --start %s\n" % (
           devpibin,
           subprocess.list2cmdline(argv))

    writer("crontab", newcrontab)
    return


def gen_nginx(tw, config, argv, writer):
    outside_url = config.args.outside_url
    if outside_url is None: # default
        outside_url = "http://localhost:80"

    parts = URL(outside_url).netloc.split(":")
    if len(parts) < 2:
        parts.append(80)
    outside_host, outside_port = parts

    nginxconf = render(tw, "nginx-devpi.conf", format=1,
                       outside_url=outside_url,
                       outside_host = outside_host,
                       outside_port = outside_port,
                       port=config.args.port,
                       serverdir=config.serverdir)
    writer("nginx-devpi.conf", nginxconf)


def gen_launchd(tw, config, argv, writer):
    devpibin = py.path.local(sys.argv[0])
    plist_content = write_plist_to_bytes(OrderedDict([
        ("Label", "net.devpi"),
        ("ProgramArguments", [str(devpibin)] + argv),
        ("RunAtLoad", True),
    ]))
    writer("net.devpi.plist", plist_content)


def gen_systemd(tw, config, argv, writer):
    import getpass
    devpibin = py.path.local(sys.argv[0])
    assert devpibin.exists()
    serverdir = config.args.serverdir
    pid_file = os.path.join(os.path.expanduser(serverdir),
                            '.xproc/devpi-server/xprocess.PID')
    content = render(
        tw, "devpi.service",
        server_args=subprocess.list2cmdline(argv),
        pid_file=pid_file,
        user=getpass.getuser(),
        devpibin=devpibin,
    )
    writer("devpi.service", content)


def genconfig(config, argv):
    tw = py.io.TerminalWriter()
    tw.cwd = py.path.local()

    destdir = tw.cwd.ensure("gen-config", dir=1)

    new_argv = [x for x in argv if x != "--gen-config"]
    new_args = parseoptions(get_pluginmanager(), ["devpi-server"] + new_argv)
    for cfg_type in ["supervisor", "nginx", "cron", "launchd", "systemd"]:
        def writer(basename, content):
            p = destdir.join(basename)
            p.write(content)
            tw.line("wrote %s" % p.relto(tw.cwd), bold=True)
        name = "gen_" + cfg_type
        globals()[name](tw, new_args, new_argv, writer)
