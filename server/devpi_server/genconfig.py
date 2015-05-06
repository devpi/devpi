from __future__ import unicode_literals
import os
import py
import sys
import subprocess
from devpi_common.url import URL

from devpi_server.config import (
    render, parseoptions, get_default_serverdir, get_pluginmanager
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

try:
    # python >= 2.7
    # prefer ordered keys for the plist
    from collections import OrderedDict as PossiblyOrderedDict
except ImportError:
    # python <= 2.6
    # we don't have OrderedDict; the plist will still be fine, but the keys
    # will be in arbitrary order
    PossiblyOrderedDict = dict

def gen_supervisor(tw, config, writer):
    import getpass
    devpibin = py.path.local(sys.argv[0])
    assert devpibin.exists()
    content = render(
            tw, "supervisord.conf",
            server_args=subprocess.list2cmdline(config.args._raw),
            user=getpass.getuser(),
            devpibin=devpibin,
    )
    writer("supervisor-devpi.conf", content)


def gen_cron(tw, config, writer):
    devpibin = py.path.local(sys.argv[0])
    newcrontab = "@reboot %s --start %s\n" % (
           devpibin,
           subprocess.list2cmdline(config.args._raw))

    writer("crontab", newcrontab)
    return


def gen_nginx(tw, config, writer):
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


def gen_launchd(tw, config, writer):
    devpibin = py.path.local(sys.argv[0])
    plist_content = write_plist_to_bytes(PossiblyOrderedDict([
        ("Label", "net.devpi"),
        ("ProgramArguments", [str(devpibin)] + config.args._raw),
        ("RunAtLoad", True),
    ]))
    writer("net.devpi.plist", plist_content)


def gen_systemd(tw, config, writer):
    import getpass
    devpibin = py.path.local(sys.argv[0])
    assert devpibin.exists()
    serverdir = config.args.serverdir
    if serverdir is None:
        serverdir = get_default_serverdir()
    pid_file = os.path.join(os.path.expanduser(serverdir),
                            '.xproc/devpi-server/xprocess.PID')
    content = render(
        tw, "devpi.service",
        server_args=subprocess.list2cmdline(config.args._raw),
        pid_file=pid_file,
        user=getpass.getuser(),
        devpibin=devpibin,
    )
    writer("devpi.service", content)


def reparse_without_genconfig(config):
    new_args = [x for x in config.args._raw if x != "--gen-config"]
    return parseoptions(get_pluginmanager(), ["devpi-server"] + new_args)

def genconfig(config):
    tw = py.io.TerminalWriter()
    tw.cwd = py.path.local()

    destdir = tw.cwd.ensure("gen-config", dir=1)

    new_config =  reparse_without_genconfig(config)
    for cfg_type in ["supervisor", "nginx", "cron", "launchd", "systemd"]:
        def writer(basename, content):
            p = destdir.join(basename)
            p.write(content)
            tw.line("wrote %s" % p.relto(tw.cwd), bold=True)
        name = "gen_" + cfg_type
        globals()[name](tw, new_config, writer)
