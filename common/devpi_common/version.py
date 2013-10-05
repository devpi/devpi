#! /usr/bin/env python
"""minimal PyPI like server for use with pip/easy_install"""

import os, re
import pkg_resources

from .vendor import _verlib as verlib
from .types import cached_property

class Version(object):
    def __init__(self, version, pep386version = None):
        assert isinstance(version, str), repr(version)
        self.version = version
        if pep386version is not None:
            self._pep386version = pep386version

    @property
    def pep386version(self):
        try:
            return self._pep386version
        except AttributeError:
            nv = verlib.suggest_normalized_version(self.version)
            if not nv:
                raise ValueError("not a PEP386 version: %r" % (self.version,))
            self._pep386version = verlib.NormalizedVersion(nv)
            return self._pep386version

    @classmethod
    def frombasename(cls, basename):
        name, ver = guess_pkgname_and_version(basename)
        return ver

    def __repr__(self):
        return "<Version %r>" %(self.version)

    def __str__(self):
        return self.version

    @cached_property
    def easyversion(self):
        return pkg_resources.parse_version(self.version)

    def __cmp__(self, other):
        return cmp(self.easyversion, other.easyversion)

    def autoinc(self):
        """ return automatically incremented version. """
        parts = self.pep386version.parts
        i = 2
        if len(parts[i]) == 1:
            i = 1
        if len(parts[i]) == 1:
            raise ValueError("cannot autoinc version %r" % self.version)
        newparts = list(parts)
        newparts[i] = (newparts[i][0], newparts[i][1]+1)
        newver = verlib.NormalizedVersion.from_parts(*newparts)
        return self.__class__(str(newver), newver)

_releasefile_suffix_rx = re.compile(r"(\.zip|\.tar\.gz|\.tgz|\.tar\.bz2|-py[23]\.\d-.*|\.win-amd64-py[23]\.\d\..*|\.win32-py[23]\.\d\..*)$", re.IGNORECASE)


def guess_pkgname_and_version(path):
    path = os.path.basename(path)
    pkgname = re.split(r"-\d+", path, 1)[0]
    version = path[len(pkgname) + 1:]
    version = _releasefile_suffix_rx.sub("", version)
    return pkgname, Version(str(version))
