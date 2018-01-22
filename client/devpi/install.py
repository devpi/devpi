import os

def main(hub, args):
    current = hub.require_valid_current_with_index()

    venv = hub.venv
    xopt = []  # not args.verbose and ["-q"] or []
    pip_path = current.getvenvbin("pip", venvdir=venv, glob=True)
    if not pip_path:
        hub.fatal("no pip binary found")
    if args.listinstalled:
        hub.info("list of installed packages on", venv)
        return hub.popen_check([pip_path, "list"])
    elif args.editable:
        if args.pkgspecs:
            hub.fatal("cannot specify packagespecs and --editable")
        args.pkgspecs = ["--editable", args.editable]

    if args.index and args.index.count("/") > 1:
        hub.fatal("index %r not of form USER/NAME or NAME" % args.index)
    simpleindex = current.get_simpleindex_url(args.index).url

    if args.pkgspecs:
        try:
            del os.environ["PYTHONDONTWRITEBYTECODE"]
        except KeyError:
            pass
        req = []
        if args.requirement:
            req.append('--requirement')
        hub.popen_check([pip_path, "install"] + xopt + [
            "-U", #"--force-reinstall",
            "-i", simpleindex] + req + list(args.pkgspecs),
            # normalize pip<1.4 and pip>=1.4 behaviour
            extraenv={"PIP_PRE": "1", "PIP_USE_WHEEL": "1"},
        )



