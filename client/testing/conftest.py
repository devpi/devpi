from __future__ import print_function
# content of conftest.py
import os
import random
import pytest
import textwrap
import py
import sys
import json

from _pytest.pytester import RunResult, LineMatcher
from devpi.main import Hub, initmain, parse_args
from devpi_common.url import URL
from test_devpi_server.conftest import reqmock  # noqa
try:
    from test_devpi_server.conftest import simpypi, simpypiserver  # noqa
except ImportError:
    # when testing with older devpi-server
    pass

import subprocess

print_ = py.builtin.print_
std = py.std

pytest_plugins = "pytester"

def pytest_addoption(parser):
    parser.addoption("--fast", help="skip functional/slow tests", default=False,
                     action="store_true")
    parser.addoption("--live-url", help="run tests against live devpi server",
                     action="store", dest="live_url")


import subprocess as gsub

def print_info(*args, **kwargs):
    kwargs.setdefault("file", sys.stderr)
    return py.builtin.print_(*args, **kwargs)

class PopenFactory:
    def __init__(self, addfinalizer):
        self.addfinalizer = addfinalizer

    def __call__(self, args, pipe=False, **kwargs):
        args = [str(x) for x in args]
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
                popen.wait()
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
    user, password = hub.current.get_auth()
    pypisubmit = hub.current.pypisubmit
    class overwrite:
        def __enter__(self):
            try:
                homedir = py.path.local._gethomedir()
            except Exception:
                pytest.skip("this test requires a home directory")
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


def _url_of_liveserver(clientdir):
    port = random.randint(2001, 64000)
    path = py.path.local.sysfind("devpi-server")
    assert path
    try:
        subprocess.check_call([
            str(path), "--serverdir", str(clientdir), "--debug",
            "--port", str(port), "--start"])
    except subprocess.CalledProcessError as e:
        print(e.output, file=sys.stderr)
        raise
    return URL("http://localhost:%s" % port)


def _stop_liveserver(clientdir):
    subprocess.check_call(["devpi-server", "--serverdir", str(clientdir),
                           "--stop"])


@pytest.yield_fixture(scope="session")
def url_of_liveserver(request):
    if request.config.option.fast:
        pytest.skip("not running functional tests in --fast mode")
    if request.config.option.live_url:
        yield URL(request.config.option.live_url)
        return
    clientdir = request.config._tmpdirhandler.mktemp("liveserver")
    yield _url_of_liveserver(clientdir)
    _stop_liveserver(clientdir)


@pytest.yield_fixture(scope="session")
def url_of_liveserver2(request):
    if request.config.option.fast:
        pytest.skip("not running functional tests in --fast mode")
    clientdir = request.config._tmpdirhandler.mktemp("liveserver2")
    yield _url_of_liveserver(clientdir)
    _stop_liveserver(clientdir)


@pytest.fixture
def devpi(cmd_devpi, gen, url_of_liveserver):
    user = gen.user()
    cmd_devpi("use", url_of_liveserver.url, code=200)
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
    def upload(name, filedefs=None, opts=()):
        initproj(name, filedefs)
        # we need to patch .pypirc
        #with devpi.patched_pypirc as reponame:
        #    popen = Popen([sys.executable, "setup.py",
        #                   "register", "-r", reponame])
        #    popen.communicate()
        #    assert popen.returncode == 0
        #    popen = Popen([sys.executable, "setup.py", "sdist", "upload",
        #                   "-r", reponame])
        #    popen.communicate()
        #    assert popen.returncode == 0
        devpi("upload", *opts)
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
                del cap
        except:
            print_(out)
            print_(err)
            raise
        print_(out)
        print_(err, file=sys.stderr)
        return RunResult(0, out.split("\n"), None, std.time.time()-now)
    return out_devpi_func

@pytest.fixture
def cmd_devpi(tmpdir, monkeypatch):
    """ execute devpi subcommand in-process (with fresh init) """
    clientdir = tmpdir.join("client")
    def run_devpi(*args, **kwargs):
        callargs = []
        for arg in ["devpi", "--clientdir", clientdir] + list(args):
            if isinstance(arg, URL):
                arg = arg.url
            callargs.append(str(arg))
        print_info("*** inline$ %s" % " ".join(callargs))
        hub, method = initmain(callargs)
        monkeypatch.setattr(hub, "ask_confirm", lambda msg: True)
        expected = kwargs.get("code", None)
        try:
            method(hub, hub.args)
        except SystemExit as sysex:
            hub.sysex = sysex
            if expected == None or expected < 0 or expected >= 400:
                # we expected an error or nothing, don't raise
                pass
            else:
                raise
        finally:
            hub.close()
        if expected is not None:
            if expected == -2:  # failed-to-start
                assert hasattr(hub, "sysex")
            elif isinstance(expected, list):
                assert hub._last_http_stati == expected
            else:
                if not isinstance(expected, tuple):
                    expected = (expected, )
                if hub._last_http_status not in expected:
                    pytest.fail("got http code %r, expected %r"
                                % (hub._last_http_status, expected))
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


@pytest.fixture
def mockhtml(monkeypatch):
    def mockhtml(cache, mockurl, content):
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
        monkeypatch.setenv("PATH", bindir + os.pathsep + os.environ["PATH"])
        return venvdir
    return do_create_venv


@pytest.fixture
def loghub(tmpdir):
    class args:
        debug = True
        clientdir = tmpdir.join("clientdir")
        yes = False
        verbose = False
    out = py.io.TextIO()
    hub = Hub(args, file=out)
    def _getmatcher():
        lines = out.getvalue().split("\n")
        return LineMatcher(lines)
    hub._getmatcher = _getmatcher
    return hub

@pytest.fixture(scope="session")
def makehub(request):
    handler = request.config._tmpdirhandler
    def mkhub(arglist):
        arglist = [str(x) for x in arglist]
        tmp = handler.mktemp("hub")
        for x in arglist:
            if "--clientdir" in x:
                break
        else:
            arglist.append("--clientdir=%s" % tmp)
        args = parse_args(["devpi_"] + arglist)
        with tmp.as_cwd():
            return Hub(args)
    return mkhub

@pytest.fixture
def mock_http_api(monkeypatch):
    """ mock out all Hub.http_api calls and return an object
    offering 'register_result' to fake replies. """
    from devpi import main
    #monkeypatch.replace("requests.session.Session.request", None)
    from requests.sessions import Session
    monkeypatch.setattr(Session, "request", None)

    class MockHTTPAPI:
        def __init__(self):
            self.called = []
            self._json_responses = {}

        def __call__(self, method, url, kvdict=None, quiet=False,
                     auth=None, basic_auth=None, cert=None,
                     fatal=True):
            kwargs = dict(
                kvdict=kvdict, quiet=quiet, auth=auth, basic_auth=basic_auth,
                cert=cert, fatal=fatal)
            self.called.append((method, url, kwargs))
            reply_data = self._json_responses.get(url)
            if reply_data is not None:
                class R:
                    status_code = reply_data["status"]
                    reason = reply_data.get("reason", "OK")
                    def json(self):
                        return reply_data["json"]
                return main.HTTPReply(R())
            pytest.fail("http_api call to %r is not mocked" % (url,))

        def set(self, url, status=200, **kw):
            data = json.loads(json.dumps(kw))
            self._json_responses[url] = {"status": status, "json": data}
    mockapi = MockHTTPAPI()
    monkeypatch.setattr(main.Hub, "http_api", mockapi)
    return mockapi

