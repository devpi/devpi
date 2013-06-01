
import py

from devpi import log
import posixpath

def main(hub, args):
    config = hub.config
    pip_path = config.getvenvbin("pip")
    if args.pkgspecs:
        hub.info("installing into", config.venvdir)
        hub.popen_check([pip_path, "install", "-U", "--force-reinstall",
            "-i", config.simpleindex ] + list(args.pkgspecs))

    if args.listinstalled:
        hub.info("list of installed packages on", config.venvdir)
        return hub.popen_check([pip_path, "freeze"])

