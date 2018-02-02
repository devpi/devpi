import os


def main(hub, args):
    current = hub.require_valid_current_with_index()

    venv = hub.venv
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
        os.environ.pop("PYTHONDONTWRITEBYTECODE", None)
        # macOS only fix, the environment variable is used to lookup the
        # Python executable and messes with pip installations in virtualenvs
        # where the installed scripts will use the global Python instead of
        # the virtualenv one if this is set
        os.environ.pop("__PYVENV_LAUNCHER__", None)
        cmd = [
            pip_path, "install",
            "-U",
            "-i", simpleindex]
        if args.requirement:
            cmd.append('--requirement')
        cmd.extend(args.pkgspecs)
        hub.popen_check(
            cmd,
            # normalize pip<1.4 and pip>=1.4 behaviour
            extraenv={"PIP_PRE": "1", "PIP_USE_WHEEL": "1"},
        )
