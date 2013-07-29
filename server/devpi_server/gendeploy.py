
import py
import sys
import os
import subprocess

from devpi_server.config import render, getpath
import devpi_server


def gendeploycfg(config, venvdir, tw=None):
    """ generate etc/ structure with supervisord.conf for running
    devpi-server under supervisor control. """
    if tw is None:
        tw = py.io.TerminalWriter()
        tw.cwd = py.path.local()

    tw.line("creating etc/ directory for supervisor configuration", bold=True)
    etc = venvdir.ensure("etc", dir=1)
    httpport = config.args.port + 1
    datadir = venvdir.ensure("data", dir=1)
    logdir = venvdir.ensure("log", dir=1)

    render(tw, etc, "supervisord.conf", venvdir=venvdir,
           devpiport=httpport,
           logdir=logdir, datadir=datadir)
    nginxconf = render(tw, etc, "nginx-devpi.conf", format=1, port=httpport,
                       datadir=datadir)
    indexurl = "http://localhost:%s/root/dev/+simple/" % httpport
    devpictl = create_devpictl(tw, venvdir, httpport)
    cron = create_crontab(tw, etc, devpictl)
    tw.line("created and configured %s" % venvdir, bold=True)
    tw.line(py.std.textwrap.dedent("""\
    You may now execute the following:

         alias devpi-ctl='%(devpictl)s'

    and then call:

        devpi-ctl start all

    after which you can configure pip to always use the default
    root/dev index which carries all pypi packages and the ones
    you upload to it::

        # content of $HOME/.pip/pip.conf
        [global]
        index-url = %(indexurl)s

    and/or easy_install and some commands like "setup develop"::

        # content of $HOME/.pydistutils.cfg
        [easy_install]
        index_url = %(indexurl)s


    %(cron)s
    As a bonus, we have prepared an nginx config at:

        %(nginxconf)s

    which you might modify and copy to your /etc/nginx/sites-enabled
    directory.
    """) % locals())
    tw.line("may quick pypi installations be with you :)", bold=True)


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


def create_devpictl(tw, tmpdir, httpport):
    devpiserver = tmpdir.join("bin", "devpi-server")
    if not devpiserver.check():
        tw.line("created fake devpictl", red=True)
        return tmpdir.join("bin", "devpi-ctl")
    firstline = devpiserver.readlines(cr=0)[0]

    devpictlpy = py.path.local(__file__).dirpath("ctl.py").read()
    devpictl = render(tw, devpiserver.dirpath(), "devpi-ctl",
                      firstline=firstline,
                      httpport=httpport, devpictlpy=devpictlpy)
    tw.line("wrote %s" % devpictl, bold=True)
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
    prefix = ""
    if devpi_ctl.check():
        tw.line("detected existing devpi-ctl, ensuring it is shut down",
                red=True)
        subproc(tw, [devpi_ctl, "shutdown", "all"])
        prefix = "re-"
    tw.line("%sinstalling virtualenv to %s" % (prefix, target), bold=True)
    try:
        del os.environ["PYTHONDONTWRITEBYTECODE"]
    except KeyError:
        pass
    subproc(tw, ["virtualenv", str(target)])
    pip = py.path.local.sysfind("pip", paths=[target.join("bin")])
    tw.line("installing devpi-server and supervisor", bold=True)
    version = devpi_server.__version__
    subproc(tw, [pip, "install", "supervisor==3.0b1", "devpi-server>=%s" % version])
    tw.line("generating configuration")
    gendeploycfg(config, target, tw=tw)

def subproc(tw, args):
    return subprocess.check_call([str(x) for x in args])
