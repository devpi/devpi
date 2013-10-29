from __future__ import unicode_literals
import py
import sys
import os
import subprocess
from devpi_common.url import urlparse

from devpi_server.config import render, getpath
import devpi_server


def gendeploycfg(config, venvdir, tw=None):
    """ generate etc/ structure with supervisord.conf for running
    devpi-server under supervisor control. """
    if tw is None:
        tw = py.io.TerminalWriter()
        tw.cwd = py.path.local()

    #tw.line("creating etc/ directory for supervisor configuration", bold=True)
    etc = venvdir.ensure("etc", dir=1)
    orig_args = list(config.args._raw)

    # filter out --gendeploy option
    for i, val in enumerate(orig_args):
        if val.startswith("--gendeploy="):
            del orig_args[i]
            break
        elif val == "--gendeploy":
            del orig_args[i:i+2]
            break

    if not config.args.serverdir:  # default
        serverdir = venvdir.ensure("data", dir=1)
    else:
        serverdir = config.serverdir
    orig_args.extend(["--serverdir", str(serverdir)])

    logdir = venvdir.ensure("log", dir=1)

    render(tw, etc, "supervisord.conf", venvdir=venvdir,
           server_args=subprocess.list2cmdline(orig_args),
           logdir=logdir)
    outside_url = config.args.outside_url
    if outside_url is None: # default
        outside_host = "localhost"
        outside_port = 80
    else:
        parsed = urlparse(outside_url)
        parts = list(parsed.netloc.split(":"))
        if len(parts) < 2:
            parts.append(80)
        outside_host, outside_port = parts

    nginxconf = render(tw, etc, "nginx-devpi.conf", format=1,
                       outside_host=outside_host,
                       outside_port=outside_port,
                       port=config.args.port,
                       serverdir=serverdir)
    devpictl = create_devpictl(tw, venvdir)
    cron = create_crontab(tw, etc, devpictl)
    tw.line("created and configured %s" % venvdir, bold=True)
    tw.line(py.std.textwrap.dedent("""\
    To control supervisor's deployment of devpi-server set:

        alias devpi-ctl='%(devpictl)s'

    and then start the server process:

        devpi-ctl start all
    %(cron)s
    We prepared an nginx configuration at:

        %(nginxconf)s

    which you might modify and copy to your /etc/nginx/sites-enabled
    directory.
    """) % locals())
    tw.line("may quick reliable pypi installations be with you :)",
            green=True)


def create_crontab(tw, etc, devpictl):
    crontab = py.path.local.sysfind("crontab")
    if crontab is None:
        return ""
    newcrontab = "@reboot %s start all\n" % devpictl
    try:
        oldcrontab = crontab.sysexec("-l")
    except py.process.cmdexec.Error:
        based = ""
    else:
        for line in oldcrontab.split("\n"):
            if line.strip()[:1] != "#" and "devpi-ctl" in line:
                return ""
        based = "(based on your current crontab)"
        newcrontab = oldcrontab.rstrip() + "\n" + newcrontab
    crontabpath = etc.join("crontab")
    crontabpath.write(newcrontab)
    tw.line("wrote %s" % crontabpath, bold=True)
    return py.std.textwrap.dedent("""\
        It seems you are using "cron", so we created a crontab file
        %s which starts devpi-server at boot. With:

            crontab %s

        you should be able to install the new crontab but please check it
        first.
    """ % (based, crontabpath))


def create_devpictl(tw, tmpdir):
    devpiserver = tmpdir.join("bin", "devpi-server")
    if not devpiserver.check():
        tw.line("created fake devpictl", red=True)
        return tmpdir.join("bin", "devpi-ctl")
    firstline = devpiserver.readlines(cr=0)[0]

    devpictlpy = py.path.local(__file__).dirpath("ctl.py").read()
    devpictl = render(tw, devpiserver.dirpath(), "devpi-ctl",
                      firstline=firstline,
                      devpictlpy=devpictlpy)
    s = py.std.stat
    setmode = s.S_IXUSR  # | s.S_IXGRP | s.S_IXOTH
    devpictl.chmod(devpictl.stat().mode | setmode)
    return devpictl


def gendeploy(config):
    tw = py.io.TerminalWriter()
    tw.cwd = py.path.local()
    if sys.platform == "win32":
        tw.line("cannot run --gendeploy on windows due to "
                "depending on supervisor.", red=True)
        return 1
    target = getpath(config.args.gendeploy)
    devpi_ctl = target.join("bin", "devpi-ctl")
    if devpi_ctl.check():
        tw.line("detected existing devpi-ctl, ensuring it is shut down",
                red=True)
        subproc(tw, [devpi_ctl, "shutdown", "all"])
    if not target.join("bin").check():
        tw.line("creating virtualenv: %s" % (target, ), bold=True)
        try:
            del os.environ["PYTHONDONTWRITEBYTECODE"]
        except KeyError:
            pass
        subproc(tw, ["virtualenv", "-q", str(target)])
    else:
        tw.line("using existing virtualenv: %s" %(target,), bold=True)
    pip = py.path.local.sysfind("pip", paths=[target.join("bin")])
    tw.line("installing devpi-server,supervisor,eventlet into virtualenv",
            bold=True)
    version = devpi_server.__version__
    subproc(tw, [pip, "install", "-q",
                 "supervisor", "eventlet", "devpi-server==%s" % version])
    gendeploycfg(config, target, tw=tw)

def subproc(tw, args):
    return subprocess.check_call([str(x) for x in args])
