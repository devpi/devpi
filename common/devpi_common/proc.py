import sys
from subprocess import Popen, CalledProcessError, PIPE

def check_output(*args, **kwargs):
    # subprocess.check_output does not exist on python26
    if "universal_newlines" not in kwargs:
        kwargs["universal_newlines"] = True
    popen = Popen(stdout=PIPE, *args, **kwargs)
    output, unused_err = popen.communicate()
    retcode = popen.poll()
    if retcode:
        cmd = kwargs.get("args")
        if cmd is None:
            cmd = args[0]
        if sys.version_info < (2,7):
            raise CalledProcessError(retcode, cmd)
        else:
            raise CalledProcessError(retcode, cmd, output=output)
    return output
