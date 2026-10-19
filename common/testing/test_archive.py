from __future__ import annotations

from devpi_common.archive import Archive
from devpi_common.archive import UnsupportedArchive
from devpi_common.archive import zip_dict
from devpi_common.archive import zip_dir
from io import BytesIO
from tarfile import TarFile
from tarfile import TarInfo
import os
import pytest


def check_files(tmpdir):
    assert tmpdir.join("1").isfile()
    assert tmpdir.join("sub", "1").isfile()


def _writetar_fromdict(
    tarfile: TarFile, contentdict: dict, prefixes: tuple = ()
) -> None:
    for name, val in contentdict.items():
        if isinstance(val, dict):
            newprefixes = (*prefixes, name)
            if not val:
                path = os.sep.join(newprefixes) + os.sep
                tarcontent = None
            else:
                _writetar_fromdict(tarfile, val, newprefixes)
                continue
        else:
            path = os.sep.join((*prefixes, name))
            tarcontent = BytesIO(val.encode("ascii") if isinstance(val, str) else val)
        tarinfo = TarInfo(path.replace(os.sep, "/"))
        if tarcontent is not None:
            tarinfo.size = len(tarcontent.getvalue())
        tarfile.addfile(tarinfo, tarcontent)


def create_tarfile_fromdict(contentdict: dict) -> bytes:
    out = BytesIO()
    with TarFile.open(fileobj=out, mode="x:gz") as tarfile:
        _writetar_fromdict(tarfile, contentdict)
    return out.getvalue()


@pytest.fixture(params=["tar", "zip"])
def archive_dict(request):
    kind = request.param

    def archive_dict(contentdict):
        if kind == "tar":
            return (kind, create_tarfile_fromdict(contentdict))
        if kind == "zip":
            return (kind, zip_dict(contentdict))
        msg = "Unknown archive kind %s" % kind
        raise RuntimeError(msg)

    return archive_dict


@pytest.fixture
def archive_path(archive_dict, tmpdir):
    contentdict = {"1": "file1", "sub": {"1": "subfile"}}
    (kind, content) = archive_dict(contentdict)
    p = tmpdir.join("content.%s" % kind)
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


@pytest.mark.parametrize("memberpath", ["/hello"])
def test_outofbound(archive_dict, memberpath, tmpdir):
    (_kind, content) = archive_dict({memberpath: ""})
    with Archive(BytesIO(content)) as archive, pytest.raises(
        ValueError, match=r"archive name '.*' out of bound"
    ):
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
