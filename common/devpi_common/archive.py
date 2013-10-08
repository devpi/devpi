"""

based on ideas/some code from Gary Wilson Jr.'s MIT-licensed archive project
(see https://pypi.python.org/pypi/Archive/0.3)
"""
import os
import py
import tarfile
import zipfile

class UnsupportedArchive(ValueError):
    pass

def get_archive(content):
    """ return ZipArchive or TarArchive object for further inspection. """
    f = py.io.BytesIO(content)
    try:
        return ZipArchive(f)
    except zipfile.BadZipfile:
        f.seek(0)
        try:
            return TarArchive(f)
        except tarfile.TarError:
            raise UnsupportedArchive()

class BaseArchive:
    class FileNotExist(ValueError):
        """ File does not exist. """
    def read(self, name):
        f = self.getfile(name)
        try:
            return f.read()
        finally:
            f.close()

class TarArchive(BaseArchive):
    def __init__(self, file):
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
