
import pytest
import py
from devpi_server.urlutil import DistURL
from devpi_server.filestore import *

class TestReleaseFileStore:
    cleanredis = True

    def test_canonical_path(self, filestore):
        canonical_relpath = filestore.canonical_relpath
        link = DistURL("https://pypi.python.org/pkg/pytest-1.2.zip#md5=123")
        relpath = canonical_relpath(link)
        parts = relpath.split("/")
        assert len(parts[0]) == filestore.HASHDIRLEN
        assert parts[1] == "pytest-1.2.zip"
        link = DistURL("https://pypi.python.org/pkg/pytest-1.2.zip")
        relpath2 = canonical_relpath(link)
        assert relpath2 == relpath
        link = DistURL("https://pypi.python.org/pkg/pytest-1.3.zip")
        relpath3 = canonical_relpath(link)
        assert relpath3 != relpath
        assert relpath3.endswith("/pytest-1.3.zip")

    def test_canonical_path_egg(self, filestore):
        canonical_relpath = filestore.canonical_relpath
        link = DistURL("https://pypi.python.org/master#egg=pytest-dev")
        relpath = canonical_relpath(link)
        parts = relpath.split("/")
        assert len(parts[0]) == filestore.HASHDIRLEN
        assert parts[1] == "pytest-dev"
        link = DistURL("https://pypi.python.org/master#egg=pytest-dev")
        relpath2 = canonical_relpath(link)


    def test_getentry_fromlink_and_maplink(self, filestore):
        link = DistURL("https://pypi.python.org/pkg/pytest-1.2.zip#md5=123")
        relpath = filestore.canonical_relpath(link)
        entry = filestore.getentry_fromlink(link)
        assert entry.relpath == relpath

    def test_maplink(self, filestore):
        link = DistURL("https://pypi.python.org/pkg/pytest-1.2.zip#md5=123")
        entry1 = filestore.maplink(link, refresh=False)
        entry2 = filestore.maplink(link, refresh=False)
        assert entry1 and entry2
        assert entry1 == entry2
        assert entry1.relpath.endswith("/pytest-1.2.zip")
        assert entry1.md5 == "123"

    def test_maplink_egg(self, filestore):
        link = DistURL("https://pypi.python.org/master#egg=pytest-dev")
        entry1 = filestore.maplink(link, refresh=False)
        entry2 = filestore.maplink(link, refresh=False)
        assert entry1 and entry2
        assert entry1 == entry2
        assert entry1.relpath.endswith("/pytest-dev")
        assert not entry1.md5
        assert entry1.url == link.url_nofrag
        assert entry1.eggfragment == "pytest-dev"

    def test_relpathentry(self, filestore):
        link = DistURL("http://pypi.python.org/pkg/pytest-1.7.zip")
        entry = filestore.getentry_fromlink(link)
        assert not entry
        entry.set(dict(url=link.url, md5="1" * 16))
        assert entry
        assert entry.url == link.url
        assert entry.md5 == "1" * 16

        # reget
        entry = filestore.getentry_fromlink(link)
        assert entry
        assert entry.url == link.url
        assert entry.md5 == "1" * 16

    def test_iterfile(self, filestore, httpget):
        link = DistURL("http://pypi.python.org/pkg/pytest-1.8.zip")
        entry = filestore.maplink(link, refresh=False)
        assert not entry.md5
        headers={"content-length": "3",
                 "last-modified": "Thu, 25 Nov 2010 20:00:27 GMT",
                 "content-type": "application/zip"}
        def iter_content(chunksize):
            yield py.builtin.bytes("12")
            yield py.builtin.bytes("3")

        httpget.url2response[link.url] = dict(status_code=200,
                headers=headers, iter_content = iter_content)
        rheaders, riter = filestore.iterfile(entry.relpath,
                                             httpget, chunksize=1)
        assert rheaders["content-length"] == "3"
        assert rheaders["content-type"] == "application/zip"
        assert rheaders["last-modified"] == headers["last-modified"]
        bytes = py.builtin.bytes().join(riter)
        assert bytes == py.builtin.bytes("123")

        # reget entry and check about content
        entry = filestore.getentry_fromlink(link)
        assert entry
        assert entry.md5 == md5(bytes).hexdigest()
        assert entry.headers == headers
        rheaders, riter = filestore.iterfile(entry.relpath, None, chunksize=1)
        assert rheaders == headers
        bytes = py.builtin.bytes().join(riter)
        assert bytes == py.builtin.bytes("123")

    def test_iterfile_eggfragment(self, filestore, httpget):
        link = DistURL("http://pypi.python.org/master#egg=pytest-dev")
        entry = filestore.maplink(link, refresh=False)
        assert entry.eggfragment
        assert entry.url
        headers={"content-length": "3",
                 "last-modified": "Thu, 25 Nov 2010 20:00:27 GMT",
                 "content-type": "application/zip"}
        l = []
        def iter_content(chunksize):
            yield py.builtin.bytes("1234")
            l.append(1)

        httpget.url2response[entry.url] = dict(status_code=200,
                headers=headers, iter_content = iter_content)
        rheaders, riter = filestore.iterfile(entry.relpath, httpget,
                                             chunksize=10)
        assert py.builtin.bytes().join(riter) == py.builtin.bytes("1234")
        assert len(l) == 1
        rheaders, riter = filestore.iterfile(entry.relpath, httpget,
                                             chunksize=10)
        assert py.builtin.bytes().join(riter) == py.builtin.bytes("1234")
        assert len(l) == 2
        # XXX we could allow getting an old version if it exists
        # and a new request errors out
        #httpget.url2response[entry.url] = dict(status_code=500)
        #rheaders, riter = store.iterfile(entry.relpath, httpget, chunksize=10)
        #assert py.builtin.bytes().join(riter) == py.builtin.bytes("1234")

