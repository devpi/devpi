import os
import sys
import py
import subprocess


def devpictl(scriptpath):
    scriptpath = py.path.local(scriptpath)
    venvdir = scriptpath.dirpath().dirpath()
    supervisorconfig = venvdir.join("etc", "supervisord.conf")
    assert supervisorconfig.check(), supervisorconfig
    ensure_supervisor_started(venvdir, supervisorconfig)
    print("using supervisor config: %s" % supervisorconfig)
    return subprocess.call(
        [str(venvdir.join("bin", "supervisorctl")),
         "-c", str(supervisorconfig)] + sys.argv[1:])

def ensure_supervisor_started(venvdir, supervisorconfig):
    pidfile = venvdir.join("supervisord.pid")
    if pidfile.check():
        pid = int(pidfile.read())
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            pass

    # we assume it's not running
    supervisord = venvdir.join("bin", "supervisord")
    subprocess.check_call([str(supervisord),
                    "-c", str(supervisorconfig)])
    print("restarted %s" % supervisord)

if __name__ == "__main__":
    raise SystemExit(devpictl(__file__))
