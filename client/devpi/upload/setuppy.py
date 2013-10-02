import os, sys

def _prepare_distutils():
    import os, sys
    from distutils.config import PyPIRCCommand

    print ("sys.argv %s" % sys.argv)
    old_read_pypirc = PyPIRCCommand._read_pypirc
    def new_read_pypirc(self):
        return {"server": "devpi",
                "repository": pypisubmit,
                "username": user,
                "password": password,
                "realm": "pypi",
               }

    PyPIRCCommand._read_pypirc = new_read_pypirc
    setupdir = sys.argv[1]
    pypisubmit = sys.argv[2]
    user = sys.argv[3]
    password = sys.argv[4]
    os.chdir(setupdir)
    # Invoking "python setup.py prepends the directory of the setup.py file.
    # (and many packages import things to obtain a version)
    sys.path.insert(0, setupdir)
    del sys.argv[:5]
    sys.argv.insert(0, "setup.py")

def run_setuppy():
    # Modify global namespace for execution of setup.py.
    namespace = globals().copy()
    namespace["__file__"] = os.path.abspath("setup.py")
    execfile("setup.py", namespace)


if __name__ == "__main__":
    _prepare_distutils()
    del _prepare_distutils
    run_setuppy()
