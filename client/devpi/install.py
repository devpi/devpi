
import os
import py

from devpi import log
import posixpath

def main(hub, args):
    current = hub.require_valid_current_with_index()

    venv = args.venv
    if venv:
        vpath = py.path.local(venv)
        if not vpath.check():
            hub.popen_check(["virtualenv", venv])
    pip_path = current.getvenvbin("pip", venvdir=venv, glob=True)
    if not pip_path:
        import pdb ; pdb.set_trace()
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
        hub.info("installing into", current.venvdir)
        hub.popen_check([pip_path, "install", "-U", "--force-reinstall",
            "-i", current.simpleindex ] + list(args.pkgspecs))


