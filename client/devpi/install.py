
import os
import py

from devpi import log
import posixpath

def main(hub, args):
    current = hub.require_valid_current_with_index()

    venv = args.venv
    if not venv:
        venv = current.venvdir
    xopt = []  # not args.verbose and ["-q"] or []
    if venv:
        vpath = py.path.local(venv)
        if not vpath.check():
            hub.popen_check(["virtualenv", "-q", venv] + xopt)
    pip_path = current.getvenvbin("pip", venvdir=venv, glob=True)
    if not pip_path:
        hub.fatal("no pip binary found")
    if args.listinstalled:
        hub.info("list of installed packages on", current.venvdir)
        return hub.popen_check([pip_path, "list"])
    elif args.editable:
        if args.pkgspecs:
            hub.fatal("cannot specify packagespecs and --editable")
        args.pkgspecs = ["--editable", args.editable]


    if args.pkgspecs:
        try:
            del os.environ["PYTHONDONTWRITEBYTECODE"]
        except KeyError:
            pass
        hub.popen_check([pip_path, "install"] + xopt + [
            #"--use-wheel",
            "--pre",
            "-U", #"--force-reinstall",
            "-i", current.simpleindex ] + list(args.pkgspecs))


