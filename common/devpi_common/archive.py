"""
remotely based on some code from https://pypi.org/project/Archive/0.3/
"""
from io import BytesIO
from pathlib import Path
import os
import tarfile
import zipfile


class UnsupportedArchive(ValueError):
    pass


def Archive(path_or_file):
    """ return in-memory Archive object, wrapping ZipArchive or TarArchive
    with uniform methods.  If an error is raised, any passed in file will
    be closed. An Archive instance acts as a context manager so that
    you can use::

        with Archive(...) as archive:
            archive.extract(...)  # or other methods

    and be sure that file handles will be closed.
    If you do not use it as a context manager, you need to call
    archive.close() yourself.
    """
    if hasattr(path_or_file, "seek"):
        f = path_or_file
    else:
        f = open(str(path_or_file), "rb")
    try:
        try:
            return ZipArchive(f)
        except zipfile.BadZipFile:
            f.seek(0)
            try:
                return TarArchive(f)
            except tarfile.TarError:
                raise UnsupportedArchive()
    except Exception:
        f.close()
        raise


class BaseArchive(object):
    class FileNotExist(ValueError):
        """ File does not exist. """
    def __init__(self, file):
        self.file = file

    def read(self, name):
        f = self.getfile(name)
        try:
            return f.read()
        finally:
            f.close()

    def close(self):
        self.file.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class TarArchive(BaseArchive):
    def __init__(self, file):
        super(TarArchive, self).__init__(file)
        self._archive = tarfile.open(mode="r", fileobj=file)

    def namelist(self, *args, **kwargs):
        return self._archive.getnames(*args, **kwargs)

    def printdir(self, *args, **kwargs):
        self._archive.list(*args, **kwargs)

    def getfile(self, name):
        try:
            member = self._archive.getmember(name)
        except KeyError:
            raise self.FileNotExist(name)
        else:
            return self._archive.extractfile(member)

    def extract(self, to_path=''):
        to_path = Path(to_path)
        members = self._archive.getmembers()
        for member in members:
            target = to_path.joinpath(member.name)
            try:
                target.relative_to(to_path)
            except ValueError as e:
                raise ValueError(
                    f"archive name {member.name!r} out of bound") from e
        self._archive.extractall(str(to_path))


class ZipArchive(BaseArchive):
    def __init__(self, file):
        super(ZipArchive, self).__init__(file)
        self._archive = zipfile.ZipFile(file)

    def printdir(self, *args, **kwargs):
        self._archive.printdir(*args, **kwargs)

    def namelist(self, *args, **kwargs):
        return self._archive.namelist(*args, **kwargs)

    def getfile(self, name):
        try:
            return self._archive.open(name)
        except KeyError:
            raise self.FileNotExist(name)

    def extract(self, to_path='', safe=False):
        # XXX unify with TarFile.extract
        basedir = Path(to_path)
        unzipfile = self._archive
        members = unzipfile.namelist()
        for name in members:
            fpath = basedir.joinpath(name)
            try:
                fpath.relative_to(basedir)
            except ValueError as e:
                raise ValueError(
                    f"archive name {name!r} out of bound") from e
            if name.endswith((os.sep, "/")):
                fpath.mkdir(parents=True, exist_ok=True)
            else:
                fpath.parent.mkdir(parents=True, exist_ok=True)
                with fpath.open("wb") as f:
                    f.write(unzipfile.read(name))


def _zip_dir(f, basedir):
    with zipfile.ZipFile(f, "w") as zf:
        _writezip(zf, basedir)


def zip_dir(basedir, dest=None):
    basedir = Path(str(basedir))
    if dest is None:
        with BytesIO() as f:
            _zip_dir(f, basedir)
            return f.getvalue()
    dest = Path(str(dest))
    with dest.open('wb') as f:
        _zip_dir(f, basedir)


def _writezip(zip, basedir):
    assert isinstance(basedir, Path)
    for p in basedir.rglob("*"):
        if p.is_dir():
            if not any(p.iterdir()):
                zipinfo = zipfile.ZipInfo(f"{p.relative_to(basedir)}/")
                zip.writestr(zipinfo, "")
        else:
            path = p.relative_to(basedir)
            zip.writestr(str(path), p.read_bytes())


def zip_dict(contentdict):
    f = BytesIO()
    zip = zipfile.ZipFile(f, "w")
    _writezip_fromdict(zip, contentdict)
    zip.close()
    return f.getvalue()


def _writezip_fromdict(zip, contentdict, prefixes=()):
    for name, val in contentdict.items():
        if isinstance(val, dict):
            newprefixes = prefixes + (name,)
            if not val:
                path = os.sep.join(newprefixes) + os.sep
                zipinfo = zipfile.ZipInfo(path)
                zip.writestr(zipinfo, "")
            else:
                _writezip_fromdict(zip, val, newprefixes)
        else:
            path = os.sep.join(prefixes + (name,))
            if isinstance(val, str):
                val = val.encode("ascii")
            zip.writestr(path, val)
