
# content of conftest.py

import pytest
import textwrap
import py
import sys
import os

print_ = py.builtin.print_
std = py.std

pytest_plugins = "pytester"

from devpi.util import url as urlutil

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
    parser.addoption("--slow", help="run functional/slow tests",
                     action="store_true")

import subprocess as gsub

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

class PyPIServerConfig:
    def __init__(self, addrstring, datadir):
        self.addrstring = addrstring
        self.datadir = datadir
        self.indexservername = "testindex"
        self.stagename = "~test/dev"
        self.user = "test"
        self.password = "test"

    @property
    def url(self, *args):
        return "http://%s/%s/pypi/" % (self.addrstring, self.stagename)

    @property
    def url_root(self, *args):
        return "http://%s/" % (self.addrstring, )

    def patchpypirc(self):
        cfg = self
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
                    index-servers = %s
                    [%s]
                    repository: %s
                    username: %s
                    password: %s
                """ % (cfg.indexservername, cfg.indexservername,
                       cfg.url, cfg.user, cfg.password))
                print ("patching .pypirc content:\n%s" % content)
                pypirc.write(content)

            def __exit__(self, *args):
                if self.saved is None:
                    self.pypirc.remove()
                else:
                    self.saved.copy(self.pypirc)
        return overwrite()

@pytest.fixture(scope="session")
def pypiserverprocess(request, xprocess, Popen_session):
    if not request.config.option.slow:
        pytest.skip("not running functional tests, use --slow to do so.")
    cfg = cfg2 = PyPIServerConfig("localhost:7999", None)

    def prepare_devpiserver(cwd):
        cfg.datadir = datadir = cwd.join("data")
        if not datadir.check():
            datadir.mkdir()
        return (".*Listening on.*",
                ["devpi-server", "--data", datadir, "--port", 7999,
                "--redisport", 7998])

    pid, logfile = xprocess.ensure("devpiserver", prepare_devpiserver,
                                   restart=True)
    assert pid is not None
    request.addfinalizer(lambda: py.process.kill(pid))
    class p:
        cfg = cfg2
    return p


@pytest.fixture
def initproj(request, tmpdir):
    from tox._pytestplugin import initproj
    return initproj(request, tmpdir)

@pytest.fixture
def create_and_upload(request, pypiserverprocess, initproj, Popen):
    def upload(name, filedefs=None):
        initproj(name, filedefs)
        cfg = pypiserverprocess.cfg
        url = cfg.url
        # we need to patch .pypirc
        with pypiserverprocess.cfg.patchpypirc():
            popen = Popen([sys.executable, "setup.py",
                           "register", "-r", cfg.indexservername])
            popen.communicate()
            assert popen.returncode == 0
            popen = Popen([sys.executable, "setup.py", "sdist", "upload",
                "-r", cfg.indexservername])
            popen.communicate()
            assert popen.returncode == 0
        return pypiserverprocess.cfg.stagename
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

    def md5(self, num=1):
        md5list = []
        for x in range(num):
            self._md5.update(str(num))
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

@pytest.fixture(scope="class")
def stageapp(request):
    from werkzeug.test import Client
    from werkzeug.wrappers import Response
    class ClientResponse(Response):
        @property
        def links(self):
            return urlutil.parselinks(self.data)

    from devpi.server.server import create_app
    tmpdir = request.config._tmpdirhandler.mktemp("stageapp", numbered=True)
    if "pypiserverprocess" in request.fixturenames:
        url = request.getfuncargvalue("pypiserverprocess").cfg.url
    else:
        url = getattr(request.cls, "upstreamurl", "http://notexists.url")
    app = create_app(tmpdir, url)
    newapp = Client(app, response_wrapper=ClientResponse)
    newapp.stageserver = app.stageserver
    return newapp


@pytest.fixture
def cmd_devpi(request, testdir):
    testdir.chdir()
    def doit(*args, **kwargs):
        testdir.chdir()
        result = runprocess(testdir.tmpdir, ["devpi"] + list(args))
        ret = kwargs.get("ret", 0)
        if ret != result.ret:
            pytest.fail("expected %s, got %s returnvalue\n%s" % (
                        ret, result.ret, result.stdout.str()))
        return result
    return doit

@pytest.fixture
def emptyhub(request, tmpdir):
    from devpi.main import Hub
    class args:
        clientdir = tmpdir.join("client")
    return Hub(args)

from _pytest.pytester import RunResult
import subprocess

def runprocess(tmpdir, cmdargs):
    cmdargs = [str(x) for x in cmdargs]
    p1 = tmpdir.join("stdout")
    print_("running", cmdargs, "curdir=", py.path.local())
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
def create_venv(request, testdir, gentmp, monkeypatch):
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
        print ac, os.environ["PATH"]
        execfile(str(ac), dict(__file__=str(ac)))
        print ac, os.environ["PATH"]
        return venvdir
    return do_create_venv

@pytest.fixture
def gentmp(request):
    """return a parametrizable temporary directory/file generator. """
    def do_gendir(name=None, scope="function"):
        node = request.node.getscopeitem(scope)
        if name:
            return basedir.ensure(name, dir=1)
        return basedir
    return do_gendir
