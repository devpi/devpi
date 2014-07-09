from __future__ import unicode_literals
import py
import sys
import subprocess
from devpi_common.url import URL

from devpi_server.config import render, parseoptions


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

def reparse_without_genconfig(config):
    new_args = [x for x in config.args._raw if x != "--gen-config"]
    return parseoptions(["devpi-server"] + new_args)

def genconfig(config):
    tw = py.io.TerminalWriter()
    tw.cwd = py.path.local()

    destdir = tw.cwd.ensure("gen-config", dir=1)

    new_config =  reparse_without_genconfig(config)
    for cfg_type in ["supervisor", "nginx", "cron"]:
        def writer(basename, content):
            p = destdir.join(basename)
            p.write(content)
            tw.line("wrote %s" % p.relto(tw.cwd), bold=True)
        name = "gen_" + cfg_type
        globals()[name](tw, new_config, writer)
