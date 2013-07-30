"""
zero-perequisites Jenkins job bootstrapping.

This script assumes it is invoked as a paramtetrized Jenkins Job,
usually triggered by a devpi webhook invocation which injects the
"indexurl" and "testspec" parameters.
"""
import os.path, sys

PY3 = sys.version_info[0] == 3

if PY3:
    from urllib.request import urlretrieve
else:
    from urllib import urlretrieve

def make_tmpdir():
    # prepare a TMPDIR that resides in the Jenkins workspace
    # this is picked up from "devpi test" below
    os.environ["TMPDIR"] = t = os.path.abspath("TMP")
    if not os.path.exists(t):
        os.makedirs(t)
    return t

def exec_bootstrap(indexurl, tmpdir):
    # get the devpibootstrap.py file which will bootstrap
    # a virtualenv and install devpi-client for running tests
    # using dependencies from the specified index
    target = os.path.join(tmpdir, "devpibootstrap.py")
    urlretrieve(indexurl + "/+bootstrap", target)
    d = {}
    execfile(target, d)
    return d["Devpi"](indexurl)


if __name__ == "__main__":
    # get Jenkins webhook-passed parameters
    indexurl = os.environ["indexurl"]
    testspec = os.environ["testspec"]

    tmpdir = make_tmpdir()
    devpi = exec_bootstrap(indexurl, tmpdir)

    # invoke the just-installed devpi
    devpi("use", indexurl)
    devpi("test", testspec)
