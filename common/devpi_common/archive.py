"""
remotely based on some code from https://pypi.python.org/pypi/Archive/0.3
"""
import tarfile
import zipfile
import py

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
        except zipfile.BadZipfile:
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
        to_path = py.path.local(to_path)
        members = self._archive.getmembers()
        for member in members:
            target = to_path.join(member.name, abs=True)
            if not target.relto(to_path):
                raise ValueError("archive name %r out of bound"
                                 %(member.name,))
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
        self._archive.extractall(str(to_path))
