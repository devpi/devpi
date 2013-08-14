
import pytest
import tarfile
import py
from devpi_server.config import render_string

bootstrapindex ="http://localhost:3141/root/dev/+simple/"

@pytest.fixture(scope="session")
def bootstrapdict():
    source = render_string("devpibootstrap.py",
       INDEXURL="http://localhost:3141/root/dev",
       VIRTUALENVTARURL=
            "http://localhost:3141/root/pypi/virtualenv-1.10.tar.gz",
       DEVPI_INSTALL_INDEX = "http://localhost:3141/root/dev",
       TESTSPEC="pytest")
    d = {}
    py.builtin.exec_(py.code.compile(source), d)
    return d

@pytest.fixture(scope="session")
def url_of_liveserver(request):
    # XXX OLD VERSION, overwritten below
    initmain = pytest.importorskip("devpi.main").initmain
    AutoServer = pytest.importorskip("devpi.server").AutoServer
    port = 7998
    clientdir = request.config._tmpdirhandler.mktemp("liveserver")
    hub, method = initmain(["devpi", "--clientdir", clientdir, "server"])
    autoserver = AutoServer(hub)
    url = "http://localhost:%s" % port
    autoserver.start(url, removedata=True)
    request.addfinalizer(autoserver.stop)
    return url

@pytest.fixture(scope="session")
def url_of_liveserver(request):
    import subprocess, random
    port = random.randint(2001, 64000)
    clientdir = request.config._tmpdirhandler.mktemp("liveserver")
    subprocess.check_call(["devpi-server", "--serverdir", str(clientdir),
                             "--port", str(port), "--start"])
    def stop():
        subprocess.check_call(["devpi-server", "--serverdir", str(clientdir),
                                 "--stop"])
    request.addfinalizer(stop)
    return "http://localhost:%s" % port

@pytest.fixture
def virtualenv_tar(tmpdir):
    base = tmpdir.mkdir("virtualenv_build")
    script = base.ensure("virtualenv-1.10", "virtualenv.py")
    script.write("#")
    tarpath = base.join("virtualenv-1.10.tar.gz")
    tar  = tarfile.open(tarpath.strpath, "w:gz")
    tar.add(str(script), script.relto(base))
    tar.close()
    print "created", tarpath.strpath
    return tarpath.strpath

def test_bootstrapdict_create(bootstrapdict):
    assert "Devpi" in bootstrapdict

def test_get_virtualenv(tmpdir, bootstrapdict, virtualenv_tar, monkeypatch):
    monkeypatch.chdir(tmpdir)
    get_virtualenv = bootstrapdict["get_virtualenv"]
    vurl = "http://localhost:3141/root/pypi/virtualenv-1.10.tar.gz"
    def urlretrieve(url, localpath):
        assert url == vurl
        py.path.local(virtualenv_tar).copy(py.path.local(localpath))
    monkeypatch.setitem(bootstrapdict, "urlretrieve", urlretrieve)
    virtualenv_script = get_virtualenv(vurl)
    assert py.std.os.path.exists(virtualenv_script)
    # check that a second attempt won't hit the web
    monkeypatch.setitem(bootstrapdict, "wget", None)
    virtualenv_script = get_virtualenv(vurl)
    assert py.std.os.path.exists(virtualenv_script)

@pytest.mark.skipif("not config.option.remote")
def test_main(request, url_of_liveserver, tmpdir, monkeypatch):
    # not a very good test as it requires going to pypi.python.org
    tmpdir.chdir()
    source = render_string("devpibootstrap.py",
       INDEXURL= url_of_liveserver + "/root/dev",
       VIRTUALENVTARURL = ("https://pypi.python.org/packages/source/"
                           "v/virtualenv/virtualenv-1.10.tar.gz"),
       DEVPI_INSTALL_INDEX = url_of_liveserver + "/root/dev/+simple/",
       TESTSPEC="py")
    d = {}
    py.builtin.exec_(py.code.compile(source), d)
    l = []
    def record(*args, **kwargs):
        l.append(args)
    monkeypatch.setattr(d["Devpi"], "run", record)
    d["main"]()
    assert len(l) == 2
    assert "use" in l[0][1]
    assert "test" in l[1][1]
