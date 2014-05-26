
import pytest
import py
from devpi_server.filestore import *

from test_extpypi import auto_transact

BytesIO = py.io.BytesIO

class TestFileStore:

    def test_maplink_deterministic(self, filestore, gen):
        link = gen.pypi_package_link("pytest-1.2.zip")
        entry1 = filestore.maplink(link)
        entry2 = filestore.maplink(link)
        assert entry1.relpath == entry2.relpath
        assert entry1.basename == "pytest-1.2.zip"
        assert py.builtin._istext(entry1.md5)

    def test_maplink_splitmd5_issue78(self, filestore, gen):
        link = gen.pypi_package_link("pytest-1.2.zip")
        entry1 = filestore.maplink(link)
        # check md5 directory structure (issue78)
        parent2 = entry1.filepath.dirpath()
        parent1 = parent2.dirpath()
        assert parent1.basename == link.md5[:3]
        assert parent2.basename == link.md5[3:]

    def test_maplink(self, filestore, gen):
        link = gen.pypi_package_link("pytest-1.2.zip")
        entry1 = filestore.maplink(link)
        entry2 = filestore.maplink(link)
        assert not entry1.iscached() and not entry2.iscached()
        assert entry1 == entry2
        assert entry1.relpath.endswith("/pytest-1.2.zip")
        assert entry1.md5 == link.md5

    def test_maplink_replaced_release_not_cached_yet(self, filestore, gen):
        link = gen.pypi_package_link("pytest-1.2.zip")
        entry1 = filestore.maplink(link)
        assert not entry1.iscached()
        assert entry1.md5 == link.md5
        newlink = gen.pypi_package_link("pytest-1.2.zip")
        entry2 = filestore.maplink(newlink)
        assert entry2.md5 == newlink.md5

    def test_maplink_replaced_release_already_cached(self, filestore, gen):
        link = gen.pypi_package_link("pytest-1.2.zip")
        entry1 = filestore.maplink(link)
        # pseudo-write a release file
        entry1.FILE.set(b"content")
        assert entry1.iscached()
        newlink = gen.pypi_package_link("pytest-1.2.zip")
        entry2 = filestore.maplink(newlink)
        assert entry2.md5 == newlink.md5
        assert not entry2.iscached()

    def test_maplink_file_there_but_no_entry(self, filestore, keyfs, gen):
        link = gen.pypi_package_link("pytest-1.2.zip")
        entry1 = filestore.maplink(link)
        entry1.FILE.set(b"hello")
        entry1.PATHENTRY.delete()
        headers, itercontent = filestore.getfile(entry1.relpath, 1)
        assert itercontent is None

    def test_invalidate_cache(self, filestore, gen):
        link = gen.pypi_package_link("pytest-1.2.zip", md5=False)
        entry1 = filestore.maplink(link)
        entry1.FILE.set(b"")
        assert entry1.iscached()
        entry1.invalidate_cache()
        assert not entry1.iscached()

    def test_maplink_egg(self, filestore, gen):
        link = gen.pypi_package_link("master#egg=pytest-dev", md5=False)
        entry1 = filestore.maplink(link)
        entry2 = filestore.maplink(link)
        assert entry1 == entry2
        assert entry1.relpath.endswith("/master")
        assert entry1.eggfragment == "pytest-dev"
        assert not entry1.md5
        assert entry1.url == link.url_nofrag
        assert entry1.eggfragment == "pytest-dev"

    def test_relpathentry(self, filestore, gen):
        link = gen.pypi_package_link("pytest-1.7.zip", md5=False)
        entry = filestore.maplink(link)
        assert entry.url == link.url
        assert not entry.iscached()
        entry.set(md5="1" * 16)
        assert not entry.iscached()
        entry.FILE.set(b"")
        assert entry.iscached()
        assert entry.url == link.url
        assert entry.md5 == u"1" * 16

        # reget
        entry = filestore.getentry(entry.relpath)
        assert entry.iscached()
        assert entry.url == link.url
        assert entry.md5 == u"1" * 16

    def test_relpathentry_size(self, filestore, gen):
        link = gen.pypi_package_link("pytest-1.7.zip")
        entry = filestore.maplink(link)
        entry.set(size=123123)
        assert py.builtin._istext(entry._mapping["size"])
        assert entry.size == u"123123"

    def test_getfile(self, filestore, httpget, gen):
        link = gen.pypi_package_link("pytest-1.8.zip", md5=False)
        entry = filestore.maplink(link)
        assert not entry.md5
        headers={"content-length": "3",
                 "last-modified": "Thu, 25 Nov 2010 20:00:27 GMT",
                 "content-type": "application/zip"}

        httpget.url2response[link.url] = dict(status_code=200,
                headers=headers, raw = BytesIO(b"123"))
        rheaders, bytes = filestore.getfile(entry.relpath,
                                            httpget, chunksize=1)
        assert rheaders["content-length"] == "3"
        assert rheaders["content-type"] == "application/zip"
        assert rheaders["last-modified"] == headers["last-modified"]
        assert bytes == b"123"

        # reget entry and check about content
        entry = filestore.getentry(entry.relpath)
        assert entry.iscached()
        assert entry.md5 == getmd5(bytes)
        assert entry.size == "3"
        rheaders, bytes = filestore.getfile(entry.relpath, None, chunksize=1)
        assert rheaders == headers
        assert bytes == b"123"

    def test_iterfile_remote_no_headers(self, filestore, httpget, gen):
        link = gen.pypi_package_link("pytest-1.8.zip", md5=False)
        entry = filestore.maplink(link)
        assert not entry.md5
        headers={}
        httpget.url2response[link.url] = dict(status_code=200,
                headers=headers, raw = BytesIO(b"123"))
        rheaders, bytes = filestore.getfile(entry.relpath,
                                            httpget, chunksize=1)
        assert rheaders["content-length"] == "3"
        assert rheaders.get("content-type") is None
        assert bytes == b"123"

    def test_iterfile_remote_error_size_mismatch(self, filestore, httpget, gen):
        link = gen.pypi_package_link("pytest-3.0.zip", md5=False)
        entry = filestore.maplink(link)
        assert not entry.md5
        headers={"content-length": "3",
                 "last-modified": "Thu, 25 Nov 2010 20:00:27 GMT",
                 "content-type": "application/zip"}
        httpget.url2response[link.url] = dict(status_code=200,
                headers=headers, raw = BytesIO(b"1"))
        with pytest.raises(ValueError):
            filestore.getfile(entry.relpath, httpget)

    def test_iterfile_remote_nosize(self, filestore, httpget, gen):
        link = gen.pypi_package_link("pytest-3.0.zip", md5=False)
        entry = filestore.maplink(link)
        assert not entry.md5
        headers={"last-modified": "Thu, 25 Nov 2010 20:00:27 GMT",
                 "content-length": None,
                 "content-type": "application/zip"}
        entry.sethttpheaders(headers)
        assert entry.size is None
        httpget.url2response[link.url] = dict(status_code=200,
                headers=headers, raw=BytesIO(b"1"))
        rheaders, received = filestore.getfile(entry.relpath,
                                               httpget, chunksize=3)
        assert received == b"1"
        entry2 = filestore.getentry(entry.relpath)
        assert entry2.size == "1"

    def test_iterfile_remote_error_md5(self, filestore, httpget, gen):
        link = gen.pypi_package_link("pytest-3.0.zip")
        entry = filestore.maplink(link)
        assert entry.md5 == link.md5
        headers={"content-length": "3",
                 "last-modified": "Thu, 25 Nov 2010 20:00:27 GMT",
                 "content-type": "application/zip"}
        httpget.url2response[link.url_nofrag] = dict(status_code=200,
                headers=headers, raw=BytesIO(b"123"))
        with pytest.raises(ValueError) as excinfo:
            filestore.getfile(entry.relpath, httpget)
        assert link.md5 in str(excinfo.value)
        assert not entry.iscached()

    @pytest.mark.xfail(reason="disambiguation of downloads from urls"
            " whose content changes over time")
    def test_iterfile_eggfragment(self, filestore, httpget, gen):
        link = gen.pypi_package_link("master#egg=pytest-dev", md5=False)
        entry = filestore.maplink(link)
        assert entry.eggfragment
        assert entry.url
        headers={"content-length": "4",
                 "last-modified": "Thu, 25 Nov 2010 20:00:27 GMT",
                 "content-type": "application/zip"}

        httpget.mockresponse(entry.url, headers=headers, raw=BytesIO(b"1234"))
        rheaders, riter = filestore.iterfile(entry.relpath, httpget,
                                             chunksize=10)
        assert py.builtin.bytes().join(riter) == b"1234"
        httpget.mockresponse(entry.url, headers=headers, raw=BytesIO(b"3333"))
        rheaders, riter = filestore.iterfile(entry.relpath, httpget,
                                             chunksize=10)
        assert b"".join(riter) == b"3333"
        # XXX we could allow getting an old version if it exists
        # and a new request errors out
        #httpget.url2response[entry.url] = dict(status_code=500)
        #rheaders, riter = store.iterfile(entry.relpath, httpget, chunksize=10)
        #assert py.builtin.bytes().join(riter) == py.builtin.bytes("1234")

    def test_store_and_iter(self, filestore):
        content = b"hello"
        entry = filestore.store("user", "index", "something-1.0.zip", content)
        assert entry.md5 == getmd5(content)
        assert entry.iscached()
        entry2 = filestore.getentry(entry.relpath)
        assert entry2.basename == "something-1.0.zip"
        assert entry2.iscached()
        assert entry2.FILE.exists()
        assert entry2.md5 == entry.md5
        assert entry2.last_modified
        headers, c = filestore.getfile(entry.relpath, httpget=None)
        assert c == content

    def test_add_testresult(self, filestore):
        #
        #link = URL("http://pypi.python.org/pkg/pytest-1.7.zip#md5=123")
        #entry = filestore.maplink(link)

        from test_devpi_server.example import tox_result_data
        md5 = tox_result_data["installpkg"]["md5"]
        data = json.dumps(tox_result_data)
        num = filestore.add_attachment(md5, "toxresult", data)
        res = filestore.get_attachment(md5, "toxresult", num)
        assert res == data
