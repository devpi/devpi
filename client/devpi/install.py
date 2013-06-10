
import py

from devpi import log
import posixpath

def main(hub, args):
    current = hub.require_valid_current_with_index()
    pip_path = current.getvenvbin("pip")
    if args.pkgspecs:
        hub.info("installing into", current.venvdir)
        hub.popen_check([pip_path, "install", "-U", "--force-reinstall",
            "-i", current.simpleindex ] + list(args.pkgspecs))

    if args.listinstalled:
        hub.info("list of installed packages on", current.venvdir)
        return hub.popen_check([pip_path, "freeze"])

