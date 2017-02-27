"""
(deprecated) perform a quickstart initialization of devpi-server and devpi-client.
"""
import pkg_resources
import py
import subprocess


def main(hub, args):
    clientdir = py.path.local(args.clientdir)
    if clientdir.dirpath("server").check():
        hub.fatal("server state directory exists, cannot perform quickstart. "
                  "If you have a server running, please kill it with "
                  "e. g. `devpi-server --stop` and "
                  "afterwards remove %s" %(clientdir.dirpath("server")))
    #out = hub.popen_output(["devpi-server", "--status"])
    #if "no server" not in out:
    #    hub.fatal("devpi-server already running, stop it first")
    (ret, out, err) = hub.popen(
        ["devpi-server", "--version"],
        dryrun=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT)
    devpi_server_version = out.decode('ascii').strip()
    devpi_args = ["devpi-server", "--start"]
    server_version = pkg_resources.parse_version(devpi_server_version)
    if server_version >= pkg_resources.parse_version('4.2.0.dev'):
        devpi_args.append('--init')
    hub.popen(devpi_args)
    try:
        hub.popen(["devpi", "use", "http://localhost:3141"])
        hub.line("")
        hub.popen(["devpi", "user", "-c", args.user,
                                   "password=%s" % args.password])
        hub.line("")
        hub.popen(["devpi", "login", args.user,
                                   "--password=%s" % args.password])
        hub.line("")
        hub.popen(["devpi", "index", "-c", args.index,])
        hub.line("")
        hub.popen(["devpi", "use", args.index,])
    except SystemExit:
        hub.line("")
        hub.info("stopping server because of failure")
        hub.popen(["devpi-server", "--stop"])
        raise SystemExit(1)

    hub.info("COMPLETED!  you can now work with your %r index" %(args.index))
    hub.info("  devpi install PKG   # install a pkg from pypi")
    hub.info("  devpi upload        # upload a setup.py based project")
    hub.info("  devpi test PKG      # download and test a tox-based project ")
    hub.info("  devpi PUSH ...      # to copy releases between indexes")
    hub.info("  devpi index ...     # to manipulate/create indexes")
    hub.info("  devpi use ...       # to change current index")
    hub.info("  devpi user ...      # to manipulate/create users")
    hub.info("  devpi CMD -h        # help for a specific command")
    hub.info("  devpi -h            # general help")
    hub.info("docs at http://doc.devpi.net")
