
import py

from devpi import log
import posixpath

def main(hub, args):
    current = hub.current
    if not current.simpleindex:
        hub.fatal("not currently using any index, see devpi current")
    pip_path = current.getvenvbin("pip")
    if args.pkgspecs:
        hub.info("installing into", current.venvdir)
        hub.popen_check([pip_path, "install", "-U", "--force-reinstall",
            "-i", current.simpleindex ] + list(args.pkgspecs))

    if args.listinstalled:
        hub.info("list of installed packages on", current.venvdir)
        return hub.popen_check([pip_path, "freeze"])

