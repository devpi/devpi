import errno
import sys
import os
import re
import signal
import subprocess
import time


def do_xkill(info):
    # return codes:
    # 0   no work to do
    # 1   killed
    # -1  failed to kill
    if not info.pid or not info.isrunning():
        return 0

    if sys.platform == "win32":
        # send a break event to all processes in the process group
        # (taskkill only kills the setuptools wrapper process)
        if hasattr(signal, "CTRL_BREAK_EVENT"):
            os.kill(info.pid, signal.CTRL_BREAK_EVENT)
            return 1
        else:
            subprocess.check_call("taskkill /F /PID %s" % info.pid)
            return 1
    else:
        try:
            os.kill(info.pid, 9)
        except OSError:
            return -1
        else:
            return 1

def do_killxshow(xprocess, tw, xkill):
    ret = 0
    for p in xprocess.rootdir.listdir():
        info = xprocess.getinfo(p.basename)
        if xkill:
            ret = do_xkill(info, tw) or ret
        else:
            running = info.isrunning() and "LIVE" or "DEAD"
            tw.line("%s %s %s %s" %(info.pid, info.name, running,
                                        info.logpath,))
    return ret

class XProcessInfo:
    def __init__(self, path, name):
        self.name = name
        self.controldir = path.ensure(name, dir=1)
        self.logpath = self.controldir.join("xprocess.log")
        self.pidpath = self.controldir.join("xprocess.PID")
        if self.pidpath.check():
            self.pid = int(self.pidpath.read())
        else:
            self.pid = None

    def kill(self):
        return do_xkill(self)

    def _isrunning_win32(self, pid):
        import ctypes, ctypes.wintypes
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(1, 0, pid)
        if handle == 0:
            return False
        exit_code = ctypes.wintypes.DWORD()
        is_running = (kernel32.GetExitCodeProcess(handle,
                        ctypes.byref(exit_code)) == 0)
        kernel32.CloseHandle(handle)
        return is_running or exit_code.value == 259

    def isrunning(self):
        if self.pid is not None:
            if sys.platform == "win32":
                return self._isrunning_win32(self.pid)
            try:
                os.kill(self.pid, 0)
                try:
                    os.waitpid(self.pid, os.WNOHANG)
                except OSError as exc:
                    if exc.errno != errno.ECHILD:
                        raise
                return True
            except OSError:
                pass
        return False


class XProcess:
    def __init__(self, config, rootdir, log=None):
        self.config = config
        self.rootdir = rootdir
        if log is None:
            class Log:
                def debug(self, msg, *args):
                    if args:
                        print(msg % args)
                    else:
                        print(args)
            log = Log()
        self.log = log

    def getinfo(self, name):
        """ return Process Info for the given external process. """
        return XProcessInfo(self.rootdir, name)

    def ensure(self, name, preparefunc, restart=False):
        """ returns (PID, logfile) from a newly started or already
            running process.

        @param name: name of the external process, used for caching info
                     across test runs.

        @param preparefunc:
                called with a fresh empty CWD for the new process,
                must return (waitpattern, args) tuple where
                ``args`` are used to start the subprocess and the
                the regular expression ``waitpattern`` must be found

        @param restart: force restarting the process if it is running.

        @return: (PID, logfile) logfile will be seeked to the end if the
                 server was running, otherwise seeked to the line after
                 where the waitpattern matched.
        """
        from subprocess import Popen, STDOUT
        info = self.getinfo(name)
        if not restart and not info.isrunning():
            restart = True

        if restart:
            if info.pid is not None:
                info.kill()
            controldir = info.controldir.ensure(dir=1)
            #controldir.remove()
            wait, args = preparefunc(controldir)
            args = [str(x) for x in args]
            self.log.debug("%s$ %s", controldir, " ".join(args))
            stdout = open(str(info.logpath), "wb", 0)
            kwargs = {}
            if sys.platform == "win32":
                kwargs["startupinfo"] = sinfo = subprocess.STARTUPINFO()

                # Protect the background process from Ctrl-C.
                if sys.version_info >= (2,7):
                    kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
                    sinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                    sinfo.wShowWindow |= subprocess.SW_HIDE
            else:
                kwargs["close_fds"] = True
                kwargs["preexec_fn"] = os.setpgrp  # no CONTROL-C
            popen = Popen(args, cwd=str(controldir),
                          stdout=stdout, stderr=STDOUT,
                          **kwargs)
            info.pid = pid = popen.pid
            info.pidpath.write(str(pid))
            self.log.debug("process %r started pid=%s", name, pid)
            stdout.close()
        f = info.logpath.open()
        if not restart:
            f.seek(0, 2)
        else:
            if not hasattr(wait, '__call__'):
                check = lambda: self._checkpattern(f, wait)
            else:
                check = wait
            if check():
                self.log.debug("%s process startup detected", name)
            else:
                raise RuntimeError("Could not start process %s" % name)
        logfiles = self.config.__dict__.setdefault("_extlogfiles", {})
        logfiles[name] = f
        return info.pid, info.logpath

    def _checkpattern(self, f, pattern, count=50):
        while 1:
            line = f.readline()
            if not line:
                time.sleep(0.1)
            self.log.debug(line)
            if re.search(pattern, line):
                return True
            count -= 1
            if count < 0:
                return False

