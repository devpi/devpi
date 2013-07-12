
# content of conftest.py

import pytest
import textwrap
import py
import sys
import os

from _pytest.pytester import RunResult, LineMatcher
from devpi.main import Hub, initmain
from devpi.server import AutoServer
import subprocess

print_ = py.builtin.print_
std = py.std

pytest_plugins = "pytester"

from devpi.util import url as urlutil

@pytest.fixture(autouse=True, scope="session")
def noautoserver():
    std.os.environ["DEVPI_NO_AUTOSERVER"] = "1"

def pytest_runtest_makereport(item, call):
    if "incremental" in item.keywords:
        if call.excinfo is not None:
            item.failed = True

def pytest_runtest_teardown(item, nextitem):
    if nextitem and getattr(item, "failed", False):
        nextitem.previousfailed = item

def pytest_runtest_setup(item):
    if "incremental" in item.keywords:
        lastitem = getattr(item, "previousfailed", None)
        if lastitem is not None:
            pytest.xfail("previous test failed (%s)" %lastitem.name)
    #else:
    #    assert 0

def pytest_addoption(parser):
    parser.addoption("--fast", help="skip functional/slow tests", default=False,
                     action="store_true")

import subprocess as gsub

def print_info(*args, **kwargs):
    kwargs.setdefault("file", sys.stderr)
    return py.builtin.print_(*args, **kwargs)

class PopenFactory:
    def __init__(self, addfinalizer):
        self.addfinalizer = addfinalizer

    def __call__(self, args, pipe=False, **kwargs):
        args = map(str, args)
        if pipe:
            print ("$ %s [piped]" %(" ".join(args),))
            popen = gsub.Popen(args, stdout=gsub.PIPE, stderr=gsub.STDOUT)
        else:
            showkwargs = " ".join(["%s=%s"] % (x,y) for x,y in kwargs.items())
            print ("$ %s %s" %(" ".join(args), showkwargs))
            popen = gsub.Popen(args, **kwargs)
        def fin():
            try:
                popen.kill()
            except OSError:
                print ("could not kill %s" % popen.pid)
        self.addfinalizer(fin)
        return popen

@pytest.fixture(scope="session")
def Popen_session(request):
    return PopenFactory(request.addfinalizer)

@pytest.fixture(scope="module")
def Popen_module(request):
    return PopenFactory(request.addfinalizer)

@pytest.fixture(scope="function")
def Popen(request):
    return PopenFactory(request.addfinalizer)

def get_pypirc_patcher(devpi):
    hub = devpi("use")
    user, password = hub.http.auth
    pypisubmit = hub.current.pypisubmit
    class overwrite:
        def __enter__(self):
            homedir = py.path.local._gethomedir()
            self.pypirc = pypirc = homedir.join(".pypirc")
            if pypirc.check():
                save = pypirc.new(basename=pypirc.basename+".save")
                pypirc.copy(save)
                self.saved = save
            else:
                self.saved = None
            content = textwrap.dedent("""
                [distutils]
                index-servers = testrepo
                [testrepo]
                repository: %s
                username: %s
                password: %s
            """ % (pypisubmit, user, password))
            print ("patching .pypirc content:\n%s" % content)
            pypirc.write(content)
            return "testrepo"

        def __exit__(self, *args):
            if self.saved is None:
                self.pypirc.remove()
            else:
                self.saved.copy(self.pypirc)
    return overwrite()

@pytest.fixture(scope="session")
def port_of_liveserver(request):
    port = 7999
    if request.config.option.fast:
        pytest.skip("not running functional tests in --fast mode")
    clientdir = request.config._tmpdirhandler.mktemp("liveserver")
    hub, method = initmain(["devpi", "--clientdir", clientdir, "server"])
    autoserver = AutoServer(hub)
    autoserver.start("http://localhost:%s" % port, removedata=True)
    request.addfinalizer(autoserver.stop)
    return port

@pytest.fixture
def devpi(cmd_devpi, gen, port_of_liveserver):
    user = gen.user()
    cmd_devpi("use", "http://localhost:%s/root/dev" % port_of_liveserver)
    cmd_devpi("user", "-c", user, "password=123", "email=123")
    cmd_devpi("login", user, "--password", "123")
    cmd_devpi("index", "-c", "dev")
    cmd_devpi("use", "dev")
    cmd_devpi.patched_pypirc = get_pypirc_patcher(cmd_devpi)
    return cmd_devpi

@pytest.fixture
def initproj(request, tmpdir):
    from tox._pytestplugin import initproj
    return initproj(request, tmpdir)

@pytest.fixture
def create_and_upload(request, devpi, initproj, Popen):
    def upload(name, filedefs=None):
        initproj(name, filedefs)
        # we need to patch .pypirc
        with devpi.patched_pypirc as reponame:
            popen = Popen([sys.executable, "setup.py",
                           "register", "-r", reponame])
            popen.communicate()
            assert popen.returncode == 0
            popen = Popen([sys.executable, "setup.py", "sdist", "upload",
                           "-r", reponame])
            popen.communicate()
            assert popen.returncode == 0
    return upload


@pytest.fixture(scope="session")
def gen():
    return Gen()

class Gen:
    def __init__(self):
        import hashlib
        self._md5 = hashlib.md5()
        self._pkgname = 0
        self._version = 0
        self._usernum = 0

    def user(self):
        self._usernum += 1
        return "user%d" % self._usernum

    def md5(self, num=1):
        md5list = []
        for x in range(num):
            self._md5.update(str(num).encode("utf8"))
            md5list.append(self._md5.hexdigest())
        if num == 1:
            return md5list[0]
        return md5list

    def resultlog(self, name="pkg1", version=None,
                  md5=None, passed=1, failed=1, skipped=1):
        from devpi.test.inject.pytest_devpi import (
            ReprResultLog, getplatforminfo)
        if version is None:
            self._version += 1
            version = "%s" % self._version

        res = ReprResultLog("/%s-%s.tgz" % (name, version),
                            md5 or self.md5(),
                            **getplatforminfo())
        out = py.io.TextIO()
        for i in range(passed):
            out.write(". test_pass.py::test_pass%s\n" %i)
        for i in range(failed):
            out.write("F test_fail.py::test_fail%s\n longrepr%s\n" %(i,i))
        for i in range(skipped):
            out.write("s test_skip.py::test_skip%s\n skiprepr%s\n" %(i,i))
        out.seek(0)
        res.parse_resultfile(out)
        res.version = version
        return res

    def releasedoc(self, stage, **kwargs):
        from devpi.server.db_couch import get_releaseid
        doc = self.releasemetadata(**kwargs)
        doc["_id"] = get_releaseid(stage, name=doc["name"],
                                   version=doc["version"])
        return doc

    def releasemetadata(self, **kwargs):
        from devpi.server.db import metadata_keys
        kw = dict([(x, u"") for x in metadata_keys])
        kw["version"] = u"0.0"
        for key, val in kwargs.items():
            assert key in kw
            kw[key] = val
        return kw

    def pkgname(self):
        self._pkgname += 1
        return "genpkg%d" % self._pkgname

    def releasefilename(self):
        pkgname = self.pkgname()
        return pkgname+"-1.0.tar.gz"


def pytest_runtest_makereport(__multicall__, item, call):
    logfiles = getattr(item.config, "_extlogfiles", None)
    if logfiles is None:
        return
    report = __multicall__.execute()
    for name in sorted(logfiles):
        content = logfiles[name].read()
        if content:
            longrepr = getattr(report, "longrepr", None)
            if hasattr(longrepr, "addsection"):
                longrepr.addsection("%s log" %name, content)
    return report

@pytest.fixture
def ext_devpi(request, tmpdir, devpi):
    def doit(*args, **kwargs):
        tmpdir.chdir()
        clientdir = devpi.clientdir
        result = runprocess(tmpdir,
            ["devpi", "--clientdir", devpi.clientdir] + list(args))
        ret = kwargs.get("ret", 0)
        if ret != result.ret:
            pytest.fail("expected %s, got %s returnvalue\n%s" % (
                        ret, result.ret, result.stdout.str()))
        return result
    return doit

@pytest.fixture
def out_devpi(devpi):
    def out_devpi_func(*args, **kwargs):
        cap = py.io.StdCaptureFD()
        cap.startall()
        now = std.time.time()
        try:
            try:
                devpi(*args, **kwargs)
            finally:
                out, err = cap.reset()
        except:
            print_(out)
            print_(err)
            raise
        print_(out)
        print_(err, file=sys.stderr)
        return RunResult(0, out.split("\n"), None, std.time.time()-now)
    return out_devpi_func

@pytest.fixture
def cmd_devpi(tmpdir):
    """ execute devpi subcommand in-process (with fresh init) """
    clientdir = tmpdir.join("client")
    def run_devpi(*args, **kwargs):
        callargs = ["devpi", "--clientdir", clientdir] + list(args)
        callargs = [str(x) for x in callargs]
        print_info("*** inline$ %s" % " ".join(callargs))
        hub, method = initmain(callargs)
        try:
            ret = method(hub, hub.args)
        except SystemExit as sysex:
            ret = sysex.args[0] or 1
        if ret and kwargs.get("code", 0) < 400:
            raise SystemExit(ret)
        hub, method = initmain(callargs)
        return hub
    run_devpi.clientdir = clientdir
    return run_devpi

@pytest.fixture
def runproc():
    return runprocess

def runprocess(tmpdir, cmdargs):
    cmdargs = [str(x) for x in cmdargs]
    p1 = tmpdir.join("stdout")
    print_info("running", cmdargs, "curdir=", py.path.local())
    with std.codecs.open(str(p1), "w", encoding="utf8") as f1:
        now = std.time.time()
        popen = subprocess.Popen(
                    cmdargs, stdout=f1, stderr=subprocess.STDOUT,
                    close_fds=(sys.platform != "win32"))
        ret = popen.wait()
    with std.codecs.open(str(p1), "r", encoding="utf8") as f1:
        outerr = f1.read().splitlines()
    return RunResult(ret, outerr, None, std.time.time()-now)


import pytest
import devpi.util.url as urlutil
from devpi import log

@pytest.fixture
def mockhtml(monkeypatch):
    def mockhtml(cache, mockurl, content):
        log.test("mock", mockurl)
        mockurl = cache._getsimpleurl(mockurl)
        old = cache.http.gethtml
        def newgethtml(url):
            if url == mockurl:
                return content
            return old(url)
        monkeypatch.setattr(cache.http, "gethtml", newgethtml)
    return mockhtml

@pytest.fixture
def create_venv(request, testdir, monkeypatch):
    monkeypatch.delenv("PYTHONDONTWRITEBYTECODE", raising=False)
    th = request.config._tmpdirhandler
    backupenv = th.ensuretemp("venvbackup")
    venvdir = th.ensuretemp("venv")
    def do_create_venv():
        if not venvdir.listdir():
            assert not backupenv.listdir()
            result = testdir.run("virtualenv", "--never-download", venvdir)
            assert result.ret == 0
            venvdir.copy(backupenv, mode=True)
        else:
            venvdir.remove()
            backupenv.copy(venvdir, mode=True)
        # activate
        if sys.platform == "win32":
            bindir = "Scripts"
        else:
            bindir = "bin"
        ac = venvdir.join(bindir, "activate_this.py")
        assert ac.check(), ac
        #print ac, os.environ["PATH"]
        execfile(str(ac), dict(__file__=str(ac)))
        #print ac, os.environ["PATH"]
        return venvdir
    return do_create_venv


@pytest.fixture
def loghub(tmpdir):
    class args:
        debug = True
        clientdir = tmpdir.join("clientdir")
    out = py.io.TextIO()
    hub = Hub(args, file=out)
    def _getmatcher():
        lines = out.getvalue().split("\n")
        return LineMatcher(lines)
    hub._getmatcher = _getmatcher
    return hub
