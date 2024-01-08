from devpi_common.archive import Archive
from devpi_common.archive import UnsupportedArchive
from devpi_common.archive import zip_dict
from devpi_common.archive import zip_dir
from io import BytesIO
from subprocess import Popen, PIPE
import pytest
import shutil
import sys


def check_files(tmpdir):
    assert tmpdir.join("1").isfile()
    assert tmpdir.join("sub", "1").isfile()


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


def create_tarfile_fromdict(tmpdir, contentdict):
    tar = shutil.which("tar")
    if not tar:
        pytest.skip("tar command not found")
    if sys.platform.startswith('win'):
        pytest.skip("tar command not working properly on Windows")
    tardir = tmpdir.join("create")
    _writedir(tardir, contentdict)
    files = [x.relto(tardir) for x in tardir.visit(lambda x: x.isfile())]
    with tardir.as_cwd():
        popen = Popen([str(tar), "cvf", "-"] + files, stdout=PIPE)
        out, err = popen.communicate()
    return out


@pytest.fixture(params=["tar", "zip"])
def archive_path(request, tmpdir):
    contentdict = {"1": "file1", "sub": {"1": "subfile"}}
    if request.param == "zip":
        content = zip_dict(contentdict)
    else:
        content = create_tarfile_fromdict(tmpdir, contentdict)
    p = tmpdir.join("content.%s" % request.param)
    p.write(content, "wb")
    return p


class TestArchive:
    @pytest.fixture(params=["path", "file"])
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
            Archive(BytesIO(b"123"))

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
    from pathlib import Path
    path = Path(__file__).parent / "data" / "slash.tar.gz"
    with Archive(path) as archive, pytest.raises(ValueError, match="archive name '.*' out of bound"):
        archive.extract(tmpdir)


def test_zip_dict(tmpdir):
    content = zip_dict({"one": {"nested": "1"}, "two": {}})
    with Archive(BytesIO(content)) as archive:
        archive.extract(tmpdir)
    assert tmpdir.join("one", "nested").read() == "1"
    assert tmpdir.join("two").isdir()


def test_zip_dir(tmpdir):
    source = tmpdir.join("source")
    newdest = tmpdir.join("newdest")
    dest = tmpdir.join("dest.zip")
    source.ensure("file")
    source.ensure("sub", "subfile")
    source.ensure("empty", dir=True)
    zip_dir(source, dest)
    with Archive(dest) as archive:
        archive.extract(newdest)
    assert newdest.join("file").isfile()
    assert newdest.join("sub", "subfile").isfile()
    assert newdest.join("empty").isdir()

    newdest.remove()
    with Archive(BytesIO(zip_dir(source))) as archive:
        archive.extract(newdest)
    assert newdest.join("file").isfile()
    assert newdest.join("sub", "subfile").isfile()
    assert newdest.join("empty").isdir()
