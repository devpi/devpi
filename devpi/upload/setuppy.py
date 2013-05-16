
def _prepare_distutils():
    import os, sys, urlparse
    from distutils.config import PyPIRCCommand

    print "sys.argv", sys.argv
    old_read_pypirc = PyPIRCCommand._read_pypirc
    def new_read_pypirc(self):
        return {"server": "devpiindex",
                "repository": pypisubmit,
                "username": "test",
                "password": "test",
                "realm": "devpi",
               }

    PyPIRCCommand._read_pypirc = new_read_pypirc
    setupdir = sys.argv[1]
    pypisubmit = sys.argv[2]
    os.chdir(setupdir)
    del sys.argv[:3]
    sys.argv.insert(0, "setup.py")

if __name__ == "__main__":
    _prepare_distutils()
    del _prepare_distutils
    execfile("setup.py", globals())

