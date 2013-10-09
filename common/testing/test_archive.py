import os
from subprocess import Popen, PIPE
import py
import pytest
from devpi_common.archive import *
datadir = py.path.local(__file__).dirpath("data")

def check_files(tmpdir):
    assert tmpdir.join("1").isfile()
    assert tmpdir.join("sub", "1").isfile()

def create_zipfile(contentdict):
    f = py.io.BytesIO()
    zip = py.std.zipfile.ZipFile(f, "w")
    _writezip(zip, contentdict)
    zip.close()
    return f.getvalue()

def _writezip(zip, contentdict, prefixes=()):
    for name, val in contentdict.items():
        if isinstance(val, dict):
            newprefixes = prefixes + (name,)
            if not val:
                path = os.sep.join(newprefixes) + os.sep
                zipinfo = py.std.zipfile.ZipInfo(path)
                zip.writestr(zipinfo, "")
            else:
                _writezip(zip, val, newprefixes)
        else:
            path = os.sep.join(prefixes + (name,))
            zip.writestr(path, val)

def _writedir(tmpdir, contentdict, prefixes=()):
    for name, val in contentdict.items():
        if isinstance(val, dict):
            newprefixes = prefixes + (name,)
            if not val:
                tmpdir.mkdir(*newprefixes)
            else:
                _writedir(tmpdir, val, newprefixes)
        else:
            tmpdir.ensure(*(prefixes + (name,))).write(val)

def create_tarfile(tmpdir, contentdict):
    tar = py.path.local.sysfind("tar")
    if not tar:
        pytest.skip("tar command not found")
    tardir = tmpdir.join("create")
    _writedir(tardir, contentdict)
    files = [x.relto(tardir) for x in tardir.visit(lambda x: x.isfile())]
    with tardir.as_cwd():
        popen = Popen([str(tar), "cvf", "-" ] + files, stdout=PIPE)
        out, err = popen.communicate()
    return out

@pytest.fixture(params=["tar", "zip"])
def archive_path(request, tmpdir):
    contentdict = {"1": "file1", "sub": {"1": "subfile"}}
    if request.param == "zip":
        content = create_zipfile(contentdict)
    else:
        content = create_tarfile(tmpdir, contentdict)
    p = tmpdir.join("content.%s" % request.param)
    p.write(content, "wb")
    return p

class TestArchive:
    @pytest.yield_fixture(params=["path", "file"])
    def archive(self, request, archive_path):
        if request.param == "path":
            arch = Archive(archive_path)
        else:
            f = archive_path.open("rb")
            arch = Archive(f)
        yield arch
        arch.close()

    def test_namelist(self, archive):
        namelist = archive.namelist()
        assert len(namelist) == 2
        assert "1" in namelist
        assert "sub/1" in namelist

    def test_unknown_archive(self):
        with pytest.raises(UnsupportedArchive):
            Archive(py.io.BytesIO(b"123"))

    def test_read(self, archive):
        assert archive.read("1") == b"file1"
        assert archive.read("sub/1") == b"subfile"

    def test_getfile(self, archive):
        assert archive.getfile("1").read() == b"file1"
        assert archive.getfile("sub/1").read() == b"subfile"

    def test_getfile_not_exists(self, archive):
        with pytest.raises(archive.FileNotExist):
            archive.getfile("123")
        assert issubclass(archive.FileNotExist, ValueError)

    def test_extract(self, archive, tmpdir):
        target = tmpdir.join("extract")
        archive.extract(target)
        assert target.join("1").read() == "file1"
        assert target.join("sub/1").read() == "subfile"

    def test_printdir(self, archive, capsys):
        archive.printdir()
        out, err = capsys.readouterr()
        assert "sub/1" in out

def test_tarfile_outofbound(tmpdir):
    with Archive(datadir.join("slash.tar.gz")) as archive:
        with pytest.raises(ValueError):
            archive.extract(tmpdir)

#def test_zipfile_outofbound(tmpdir):
#    archive = get_archive(datadir.join("slash.zip").read())
#    with pytest.raises(ValueError):
#        archive.extract(tmpdir)
