from __future__ import print_function
from contextlib import closing
from devpi_common.metadata import parse_version
from io import BytesIO
from io import StringIO
import codecs
import os
import pytest
import socket
import textwrap
import py
import sys
import json
import time

from .reqmock import reqmock  # noqa
from devpi.main import Hub, get_pluginmanager, initmain, parse_args
from devpi_common.url import URL

import subprocess


# BBB for Python 2.7
try:
    basestring
except NameError:
    basestring = str


def pytest_addoption(parser):
    parser.addoption(
        "--devpi-server-requirements",
        help="devpi-server requirements to install in virtualenv",
        action="append")
    parser.addoption("--fast", help="skip functional/slow tests", default=False,
                     action="store_true")
    parser.addoption("--live-url", help="run tests against live devpi server",
                     action="store", dest="live_url")


def print_info(*args, **kwargs):
    kwargs.setdefault("file", sys.stderr)
    return print(*args, **kwargs)


class PopenFactory:
    def __init__(self, addfinalizer):
        self.addfinalizer = addfinalizer

    def __call__(self, args, pipe=False, **kwargs):
        args = [str(x) for x in args]
        if pipe:
            print("$ %s [piped]" %(" ".join(args),))
            popen = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        else:
            showkwargs = " ".join(["%s=%s"] % (x,y) for x,y in kwargs.items())
            print("$ %s %s" %(" ".join(args), showkwargs))
            popen = subprocess.Popen(args, **kwargs)

        def fin():
            try:
                popen.kill()
                popen.wait()
            except OSError:
                print("could not kill %s" % popen.pid)

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


@pytest.fixture(scope="session")
def simpypiserver():
    from .simpypi import httpserver, SimPyPIRequestHandler
    import threading
    host = 'localhost'
    port = get_open_port(host)
    server = httpserver.HTTPServer((host, port), SimPyPIRequestHandler)
    thread = threading.Thread(target=server.serve_forever)
    thread.daemon = True
    thread.start()
    wait_for_port(host, port, 5)
    print("Started simpypi server %s:%s" % server.server_address)
    return server


@pytest.fixture
def simpypi(simpypiserver):
    from .simpypi import SimPyPI
    simpypiserver.simpypi = SimPyPI(simpypiserver.server_address)
    return simpypiserver.simpypi


def get_open_port(host):
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        s.bind((host, 0))
        s.listen(1)
        port = s.getsockname()[1]
    return port


def wait_for_port(host, port, timeout=60):
    while timeout > 0:
        with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
            s.settimeout(1)
            if s.connect_ex((host, port)) == 0:
                return
        time.sleep(1)
        timeout -= 1
    raise RuntimeError(
        "The port %s on host %s didn't become accessible" % (port, host))


def find_python3():
    locations = [
        "C:\\Python37-x64\\python.exe",
        "C:\\Python37\\python.exe",
        "C:\\Python38-x64\\python.exe",
        "C:\\Python38\\python.exe",
        "C:\\Python39-x64\\python.exe",
        "C:\\Python39\\python.exe"]
    for location in locations:
        if not os.path.exists(location):
            continue
        try:
            output = subprocess.check_output([location, '--version'])
            if output.strip().startswith(b'Python 3'):
                return location
        except subprocess.CalledProcessError:
            continue
    names = [
        'python3.7',
        'python3.8',
        'python3.9',
        'python3']
    for name in names:
        path = py.path.local.sysfind(name)
        if not path:
            continue
        path = str(path)
        try:
            print("Checking %s at %s" % (name, path))
            output = subprocess.check_output([path, '--version'])
            if output.strip().startswith(b'Python 3'):
                return path
        except subprocess.CalledProcessError:
            continue
    raise RuntimeError("Can't find a Python 3 executable.")


def get_venv_script(venv_path, script_names):
    for bindir in ('Scripts', 'bin'):
        for script_name in script_names:
            script = venv_path.join(bindir, script_name)
            if script.exists():
                return str(script)
    else:
        raise RuntimeError("Can't find %s in %s." % (script_names, venv_path))


@pytest.fixture(scope="session")
def server_executable(request, tmpdir_factory):
    if request.config.option.fast:
        pytest.skip("not running functional tests in --fast mode")
    requirements = request.config.option.devpi_server_requirements
    if not requirements:
        requirements = ['devpi-server>=6dev']
        # first try installed devpi-server for quick runs during development
        path = py.path.local.sysfind("devpi-server")
        if path:
            print("server_executable: Using existing devpi-server at %s" % path)
            return str(path)
    # there is no devpi-server installed
    python3 = find_python3()
    # prepare environment for subprocess call
    env = dict(os.environ)
    env.pop("VIRTUALENV_PYTHON", None)
    env.pop("VIRTUAL_ENV", None)
    if sys.platform != "win32":
        env.pop("PATH", None)
    # create a virtualenv with Python 3
    venv_path = tmpdir_factory.mktemp("server_venv")
    subprocess.check_call(
        [sys.executable, '-m', 'virtualenv', '-p', python3, str(venv_path)],
        env=env)
    # install devpi-server
    venv_pip = get_venv_script(venv_path, ('pip', 'pip.exe'))
    print("server_executable: Installing %r with %s" % (requirements, venv_pip))
    subprocess.check_call(
        [venv_pip, 'install', '--pre'] + requirements,
        env=env)
    return get_venv_script(venv_path, ('devpi-server', 'devpi-server.exe'))


@pytest.fixture(scope="session")
def server_version(server_executable):
    try:
        output = subprocess.check_output([server_executable, "--version"])
        return parse_version(output.decode('ascii').strip())
    except subprocess.CalledProcessError as e:
        # this won't output anything on Windows
        print(
            getattr(e, 'output', "Can't get process output on Windows"),
            file=sys.stderr)
        raise


@pytest.fixture(scope="session")
def indexer_backend_option(server_executable):
    out = subprocess.check_output([server_executable, '-h'])
    if b'--indexer-backend' in out:
        return ['--indexer-backend', 'null']
    return []


def _liveserver(clientdir, indexer_backend_option, server_executable, server_version):
    host = 'localhost'
    port = get_open_port(host)
    try:
        args = [
            "--serverdir", str(clientdir)]
        init_executable = server_executable.replace(
            "devpi-server", "devpi-init")
        subprocess.check_call([init_executable] + args)
    except subprocess.CalledProcessError as e:
        # this won't output anything on Windows
        print(
            getattr(e, 'output', "Can't get process output on Windows"),
            file=sys.stderr)
        raise
    args.extend(indexer_backend_option)
    p = subprocess.Popen([server_executable] + args + [
        "--debug", "--host", host, "--port", str(port)])
    wait_for_port(host, port)
    return (p, URL("http://%s:%s" % (host, port)))


@pytest.fixture(scope="session")
def url_of_liveserver(request, indexer_backend_option, server_executable, server_version, tmpdir_factory):
    if request.config.option.fast:
        pytest.skip("not running functional tests in --fast mode")
    if request.config.option.live_url:
        yield URL(request.config.option.live_url)
        return
    clientdir = tmpdir_factory.mktemp("liveserver")
    (p, url) = _liveserver(clientdir, indexer_backend_option, server_executable, server_version)
    try:
        yield url
    finally:
        p.terminate()
        p.wait()


@pytest.fixture(scope="session")
def url_of_liveserver2(request, indexer_backend_option, server_executable, server_version, tmpdir_factory):
    if request.config.option.fast:
        pytest.skip("not running functional tests in --fast mode")
    clientdir = tmpdir_factory.mktemp("liveserver2")
    (p, url) = _liveserver(clientdir, indexer_backend_option, server_executable, server_version)
    try:
        yield url
    finally:
        p.terminate()
        p.wait()


@pytest.fixture
def devpi_username(gen):
    return gen.user()


@pytest.fixture
def devpi(cmd_devpi, devpi_username, url_of_liveserver):
    user = devpi_username
    cmd_devpi("use", url_of_liveserver.url, code=200)
    cmd_devpi("user", "-c", user, "password=123", "email=123")
    cmd_devpi("login", user, "--password", "123")
    cmd_devpi("index", "-c", "dev")
    cmd_devpi("use", "dev")
    return cmd_devpi


def _path_parts(path):
    path = path and str(path)  # py.path.local support
    parts = []
    while path:
        folder, name = os.path.split(path)
        if folder == path:  # root folder
            folder, name = name, folder
        if name:
            parts.append(name)
        path = folder
    parts.reverse()
    return parts


def _path_join(base, *args):
    # workaround for a py.path.local bug on Windows (`path.join('/x', abs=1)`
    # should be py.path.local('X:\\x') where `X` is the current drive, when in
    # fact it comes out as py.path.local('\\x'))
    return py.path.local(base.join(*args, abs=1))


def _filedefs_contains(base, filedefs, path):
    """
    whether `filedefs` defines a file/folder with the given `path`

    `path`, if relative, will be interpreted relative to the `base` folder, and
    whether relative or not, must refer to either the `base` folder or one of
    its direct or indirect children. The base folder itself is considered
    created if the filedefs structure is not empty.

    """
    unknown = object()
    base = py.path.local(base)
    path = _path_join(base, path)

    path_rel_parts = _path_parts(path.relto(base))
    for part in path_rel_parts:
        if not isinstance(filedefs, dict):
            return False
        filedefs = filedefs.get(part, unknown)
        if filedefs is unknown:
            return False
    return path_rel_parts or path == base and filedefs


def create_files(base, filedefs):
    for key, value in filedefs.items():
        if isinstance(value, dict):
            create_files(base.ensure(key, dir=1), value)
        elif isinstance(value, basestring):
            s = textwrap.dedent(value)
            base.join(key).write(s)


@pytest.fixture
def initproj(tmpdir):
    """Create a factory function for creating example projects.

    Constructed folder/file hierarchy examples:

    with `src_root` other than `.`:

      tmpdir/
          name/                  # base
            src_root/            # src_root
                name/            # package_dir
                    __init__.py
                name.egg-info/   # created later on package build
            setup.py

    with `src_root` given as `.`:

      tmpdir/
          name/                  # base, src_root
            name/                # package_dir
                __init__.py
            name.egg-info/       # created later on package build
            setup.py
    """

    def initproj_(nameversion, filedefs=None, src_root=".", kind="setup.py"):
        if filedefs is None:
            filedefs = {}
        if not src_root:
            src_root = "."
        if isinstance(nameversion, basestring):
            parts = nameversion.split(str("-"))
            if len(parts) == 1:
                parts.append("0.1")
            name, version = parts
        else:
            name, version = nameversion
        base = tmpdir.join(name)
        src_root_path = _path_join(base, src_root)
        assert base == src_root_path or src_root_path.relto(
            base
        ), "`src_root` must be the constructed project folder or its direct or indirect subfolder"

        base.ensure(dir=1)
        create_files(base, filedefs)
        if not _filedefs_contains(base, filedefs, "setup.py") and kind == "setup.py":
            create_files(
                base,
                {
                    "setup.py": """
                from setuptools import setup, find_packages
                setup(
                    name='{name}',
                    description='{name} project',
                    version='{version}',
                    license='MIT',
                    platforms=['unix', 'win32'],
                    packages=find_packages('{src_root}'),
                    package_dir={{'':'{src_root}'}},
                )
            """.format(
                        **locals()
                    )
                },
            )
        if not _filedefs_contains(base, filedefs, "pyproject.toml") and kind == "setup.cfg":
            create_files(base, {"pyproject.toml": """
                    [build-system]
                    requires = ["setuptools", "wheel"]
                """})
        if not _filedefs_contains(base, filedefs, "setup.cfg") and kind == "setup.cfg":
            create_files(base, {"setup.cfg": """
                    [metadata]
                    name = {name}
                    description= {name} project
                    version = {version}
                    license = MIT
                    packages = find:
                """.format(**locals())})
        if not _filedefs_contains(base, filedefs, "pyproject.toml") and kind == "pyproject.toml":
            create_files(base, {"pyproject.toml": """
                    [build-system]
                    requires = ["flit_core >=3.2"]
                    build-backend = "flit_core.buildapi"

                    [project]
                    name = "{name}"
                    description= "{name} project"
                    version = "{version}"
                    license = {{text="MIT"}}
                    packages = "find:"
                """.format(**locals())})
        if not _filedefs_contains(base, filedefs, src_root_path.join(name)):
            create_files(
                src_root_path, {name: {"__init__.py": "__version__ = {!r}".format(version)}}
            )
        manifestlines = [
            "include {}".format(p.relto(base)) for p in base.visit(lambda x: x.check(file=1))
        ]
        create_files(base, {"MANIFEST.in": "\n".join(manifestlines)})
        print("created project in {}".format(base))
        base.chdir()
        return base

    return initproj_


@pytest.fixture
def create_and_upload(request, devpi, initproj, Popen):
    def upload(name, filedefs=None, opts=()):
        initproj(name, filedefs)
        devpi("upload", "--no-isolation", *opts)
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
        out = StringIO()
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
        kw = {x: u"" for x in metadata_keys}
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


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    logfiles = getattr(item.config, "_extlogfiles", None)
    if logfiles is None:
        return
    report = outcome.get_result()
    for name in sorted(logfiles):
        content = logfiles[name].read()
        if content:
            longrepr = getattr(report, "longrepr", None)
            if hasattr(longrepr, "addsection"):
                longrepr.addsection("%s log" %name, content)


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
        from _pytest.pytester import RunResult
        cap = py.io.StdCaptureFD()
        cap.startall()
        now = time.time()
        ret = 0
        try:
            try:
                hub = devpi(*args, **kwargs)
                if getattr(hub, "sysex", None):
                    ret = hub.sysex.args[0]
            finally:
                out, err = cap.reset()
                del cap
        except:
            print(out)
            print(err)
            raise
        print(out)
        print(err, file=sys.stderr)
        return RunResult(ret, out.split("\n"), None, time.time()-now)
    return out_devpi_func


@pytest.fixture
def cmd_devpi(tmpdir, monkeypatch):
    """ execute devpi subcommand in-process (with fresh init) """
    def ask_confirm(msg):
        print("%s: yes" % msg)
        return True
    clientdir = tmpdir.join("client")

    def run_devpi(*args, **kwargs):
        callargs = []
        for arg in ["devpi", "--clientdir", clientdir] + list(args):
            if isinstance(arg, URL):
                arg = arg.url
            callargs.append(str(arg))
        print_info("*** inline$ %s" % " ".join(callargs))
        hub, method = initmain(callargs)
        monkeypatch.setattr(hub, "ask_confirm", ask_confirm)
        expected = kwargs.get("code", None)
        try:
            method(hub, hub.args)
        except SystemExit as sysex:
            hub.sysex = sysex
            if expected is None or expected < 0 or expected >= 400:
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
    from _pytest.pytester import RunResult
    cmdargs = [str(x) for x in cmdargs]
    p1 = tmpdir.join("stdout")
    print_info("running", cmdargs, "curdir=", py.path.local())
    with codecs.open(str(p1), "w", encoding="utf8") as f1:
        now = time.time()
        popen = subprocess.Popen(
                    cmdargs, stdout=f1, stderr=subprocess.STDOUT,
                    close_fds=(sys.platform != "win32"))
        ret = popen.wait()
    with codecs.open(str(p1), "r", encoding="utf8") as f1:
        outerr = f1.read().splitlines()
    return RunResult(ret, outerr, None, time.time()-now)


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
def create_venv(request, tmpdir_factory, monkeypatch):
    monkeypatch.delenv("PYTHONDONTWRITEBYTECODE", raising=False)
    venvdir = tmpdir_factory.mktemp("venv")
    venvinstalldir = tmpdir_factory.mktemp("inst")

    def do_create_venv():
        # we need to change directory, otherwise the path will become
        # too long on windows
        venvinstalldir.ensure_dir()
        os.chdir(venvinstalldir.strpath)
        subprocess.check_call([
            "virtualenv", "--never-download", venvdir.strpath])
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
    from _pytest.pytester import LineMatcher

    class args:
        debug = True
        clientdir = tmpdir.join("clientdir")
        yes = False
        verbose = False
        settrusted = False

    # BBB for Python 2.7
    if sys.version_info < (3,):
        out = BytesIO()
    else:
        out = StringIO()
    hub = Hub(args, file=out)

    def _getmatcher():
        lines = out.getvalue().split("\n")
        return LineMatcher(lines)

    hub._getmatcher = _getmatcher
    return hub


@pytest.fixture(scope="session")
def makehub(tmpdir_factory):
    def mkhub(arglist):
        arglist = [str(x) for x in arglist]
        tmp = tmpdir_factory.mktemp("hub")
        for x in arglist:
            if "--clientdir" in x:
                break
        else:
            arglist.append("--clientdir=%s" % tmp)
        pm = get_pluginmanager()
        args = parse_args(["devpi_"] + arglist, pm)
        with tmp.as_cwd():
            return Hub(args)
    return mkhub


@pytest.fixture
def mock_http_api(monkeypatch, reqmock):  # noqa
    """ mock out all Hub.http_api calls and return an object
    offering 'set' and 'add' to fake replies. """
    from devpi import main

    class MockHTTPAPI:
        def __init__(self):
            self.called = []
            self._json_responses = {}

        def __call__(self, method, url, kvdict=None, quiet=False,
                     auth=None, basic_auth=None, cert=None,
                     check_version=True, fatal=True, type=None, verify=None):
            kwargs = {
                "kvdict": kvdict, "quiet": quiet, "auth": auth, "basic_auth": basic_auth,
                "cert": cert, "fatal": fatal}
            self.called.append((method, url, kwargs))
            reply_data = self._json_responses.get(url)
            if isinstance(reply_data, list):
                if not reply_data:
                    pytest.fail(
                        "http_api call to %r has no further replies" % (url,))
                reply_data = reply_data.pop(0)
            if reply_data is None:
                pytest.fail("http_api call to %r is not mocked" % (url,))

            class R:
                status_code = reply_data["status"]
                reason = reply_data.get("reason", "OK")

                def json(self):
                    return reply_data["json"]

            return main.HTTPReply(R())

        def set(self, url, status=200, **kw):
            """ Set a reply for all future uses. """
            data = json.loads(json.dumps(kw))
            self._json_responses[url] = {"status": status, "json": data}

        def add(self, url, status=200, **kw):
            """ Add a one time use reply to the url. """
            data = json.loads(json.dumps(kw))
            self._json_responses.setdefault(url, []).append(
                {"status": status, "json": data})

    mockapi = MockHTTPAPI()
    monkeypatch.setattr(main.Hub, "http_api", mockapi)
    return mockapi
