
import pytest
import tarfile
import py
from devpi_server.config import render_string

bootstrapindex ="http://localhost:3141/root/dev/+simple/"

@pytest.fixture(scope="session")
def bootstrapdict():
    source = render_string("devpibootstrap.py",
       virtualenvtar="http://localhost:3141/root/pypi/virtualenv-1.10.tar.gz",
       bootstrapindex=bootstrapindex)
    d = {}
    py.builtin.exec_(py.code.compile(source), d)
    return d


@pytest.fixture
def virtualenv_tar(tmpdir):
    base = tmpdir.mkdir("virtualenv_build")
    script = base.ensure("virtualenv-1.10", "virtualenv.py")
    script.write("#")
    tarpath = base.join("virtualenv-1.10.tar.gz")
    with tarfile.open(tarpath.strpath, "w:gz") as tar:
        tar.add(str(script), script.relto(base))
    print "created", tarpath.strpath
    return tarpath.strpath

def test_bootstrapdict_create(bootstrapdict):
    assert "Devpi" in bootstrapdict

def test_get_virtualenv(bootstrapdict, virtualenv_tar, monkeypatch):
    get_virtualenv = bootstrapdict["get_virtualenv"]
    def wget(url):
        assert url == "http://localhost:3141/root/pypi/virtualenv-1.10.tar.gz"
        return str(virtualenv_tar)
    monkeypatch.setitem(bootstrapdict, "wget", wget)
    virtualenv_script = get_virtualenv()
    assert py.std.os.path.exists(virtualenv_script)
    monkeypatch.setitem(bootstrapdict, "wget", None)
    virtualenv_script = get_virtualenv()
    assert py.std.os.path.exists(virtualenv_script)
