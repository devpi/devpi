import hashlib
import pytest
import py


zip_types = ("application/zip", "application/x-zip-compressed")

BytesIO = py.io.BytesIO

def getdigest(content, hash_type):
    return getattr(hashlib, hash_type)(content).hexdigest()


@pytest.mark.writetransaction
class TestFileStore:
    def test_maplink_deterministic(self, filestore, gen):
        link = gen.pypi_package_link("pytest-1.2.zip")
        entry1 = filestore.maplink(link, "root", "pypi", "pytest")
        entry2 = filestore.maplink(link, "root", "pypi", "pytest")
        assert entry1.relpath == entry2.relpath
        assert entry1.basename == entry2.basename == "pytest-1.2.zip"
        assert py.builtin._istext(entry1.hash_spec)

    @pytest.mark.parametrize("hash_spec", [
        "sha256=%s" %(hashlib.sha256(b'qwe').hexdigest()),
        "md5=%s" %(hashlib.md5(b'qwe').hexdigest()),
    ])
    def test_maplink_splithashdir_issue78(self, filestore, gen, hash_spec):
        link = gen.pypi_package_link("pytest-1.2.zip#" + hash_spec, md5=False)
        entry1 = filestore.maplink(link, "root", "pypi", "pytest")
        # check md5 directory structure (issue78)
        parts = entry1.relpath.split("/")
        parent2 = parts[-2]
        parent1 = parts[-3]
        assert parent1 == link.hash_value[:3]
        assert parent2 == link.hash_value[3:16]
        assert getattr(hashlib, hash_spec.split("=")[0]) == link.hash_algo

    def test_maplink(self, filestore, gen):
        link = gen.pypi_package_link("pytest-1.2.zip")
        entry1 = filestore.maplink(link, "root", "pypi", "pytest")
        entry2 = filestore.maplink(link, "root", "pypi", "pytest")
        assert not entry1.file_exists() and not entry2.file_exists()
        assert entry1 == entry2
        assert entry1.relpath.endswith("/pytest-1.2.zip")
        assert entry1.hash_spec == link.hash_spec
        assert entry1.project == "pytest"

    @pytest.mark.parametrize(("releasename", "project", "version"), [
        ("pytest-2.3.4.zip", "pytest", "2.3.4"),
        ("pytest-2.3.4-py27.egg", "pytest", "2.3.4"),
        ("dddttt-0.1.dev38-py2.7.egg", "dddttt", "0.1.dev38"),
        ("devpi-0.9.5.dev1-cp26-none-linux_x86_64.whl", "devpi", "0.9.5.dev1"),
        ("wheel-0.21.0-py2.py3-none-any.whl", "wheel", "0.21.0"),
        ("green-0.4.0-py2.5-win32.egg", "green", "0.4.0"),
        ("Candela-0.2.1.macosx-10.4-x86_64.exe", "Candela", "0.2.1"),
        ("Cambiatuscromos-0.1.1alpha.linux-x86_64.exe", "Cambiatuscromos", "0.1.1alpha"),
        ("Aesthete-0.4.2.win32.exe", "Aesthete", "0.4.2"),
        ("DTL-1.0.5.win-amd64.exe", "DTL", "1.0.5"),
        ("Cheetah-2.2.2-1.x86_64.rpm", "Cheetah", "2.2.2-1"),
        ("Cheetah-2.2.2-1.src.rpm", "Cheetah", "2.2.2-1"),
        ("Cheetah-2.2.2-1.x85.rpm", "Cheetah", "2.2.2-1"),
        ("Cheetah-2.2.2.dev1.x85.rpm", "Cheetah", "2.2.2.dev1"),
        ("Cheetah-2.2.2.dev1.noarch.rpm", "Cheetah", "2.2.2.dev1"),
        ("deferargs.tar.gz", "", ""),
        ("hello-1.0.doc.zip", "hello", "1.0"),
        ("Twisted-12.0.0.win32-py2.7.msi", "Twisted", "12.0.0"),
        ("django_ipware-0.0.8-py3-none-any.whl", "django_ipware", "0.0.8"),
        ("my-binary-package-name-1-4-3-yip-0.9.tar.gz", "my-binary-package-name-1-4-3-yip", "0.9"),
        ("my-binary-package-name-1-4-3-yip-0.9+deadbeef.tar.gz", "my-binary-package-name-1-4-3-yip", "0.9+deadbeef"),
        ("cffi-1.6.0-pp251-pypy_41-macosx_10_11_x86_64.whl", "cffi", "1.6.0"),
        ("argon2_cffi-18.2.0.dev0.0-pp2510-pypy_41-macosx_10_13_x86_64.whl", "argon2_cffi", "18.2.0.dev0.0"),
    ])
    def test_maplink_project_version(self, filestore, gen, releasename, project, version):
        link = gen.pypi_package_link(releasename)
        entry = filestore.maplink(link, "root", "pypi", project)
        assert entry.relpath.endswith("/" + releasename)
        assert entry.project == project
        assert entry.version == version

    def test_maplink_project_bad_archive(self, filestore, gen):
        link = gen.pypi_package_link("pytest-1.0.foo")
        entry = filestore.maplink(link, "root", "pypi", "pytest")
        assert entry.relpath.endswith("/pytest-1.0.foo")
        assert entry.project == "pytest"
        # the unknown file type prevents us from getting the version
        assert entry.version is None

    def test_maplink_replaced_release_not_cached_yet(self, filestore, gen):
        link = gen.pypi_package_link("pytest-1.2.zip")
        entry1 = filestore.maplink(link, "root", "pypi", "pytest")
        assert not entry1.file_exists()
        assert entry1.hash_spec and entry1.hash_spec == link.hash_spec
        newlink = gen.pypi_package_link("pytest-1.2.zip")
        entry2 = filestore.maplink(newlink, "root", "pypi", "pytest")
        assert entry2.hash_spec and entry2.hash_spec == newlink.hash_spec

    def test_maplink_replaced_release_already_cached(self, filestore, gen):
        content1 = b'somedata'
        md5_1 = hashlib.md5(content1).hexdigest()
        link1 = gen.pypi_package_link("pytest-1.2.zip", md5=md5_1)
        entry1 = filestore.maplink(link1, "root", "pypi", "pytest")
        # pseudo-write a release file with a specific hash_spec
        entry1.file_set_content(content1, hash_spec="md5=" + md5_1)
        assert entry1.file_exists()
        # make sure the entry has the same hash_spec as the external link
        assert entry1.hash_spec and entry1.hash_spec == link1.hash_spec

        # now replace the hash of the link and check again
        content2 = b'otherdata'
        md5_2 = hashlib.md5(content2).hexdigest()
        link2 = gen.pypi_package_link("pytest-1.2.zip", md5=md5_2)
        entry2 = filestore.maplink(link2, "root", "pypi", "pytest")
        assert entry2.hash_spec and entry2.hash_spec == link2.hash_spec
        assert not entry2.file_exists()

    @pytest.mark.storage_with_filesystem
    def test_file_exists_new_hash(self, filestore, gen):
        content1 = b'somedata'
        md5_1 = hashlib.md5(content1).hexdigest()
        link1 = gen.pypi_package_link("pytest-1.2.zip", md5=md5_1)
        entry1 = filestore.maplink(link1, "root", "pypi", "pytest")
        # write a wrong file outside the transaction
        filepath = filestore.storedir.join(entry1.relpath)
        py.path.local(filepath).dirpath().ensure(dir=1)
        with filepath.open("w") as f:
            f.write('othercontent')
        filestore.keyfs.rollback_transaction_in_thread()
        filestore.keyfs.begin_transaction_in_thread(write=True)
        # now check if the file got replaced
        entry2 = filestore.maplink(link1, "root", "pypi", "pytest")
        assert not entry2.file_exists()
        filestore.keyfs.commit_transaction_in_thread()
        assert not py.path.local(filepath).exists()

    def test_file_delete(self, filestore, gen):
        link = gen.pypi_package_link("pytest-1.2.zip", md5=False)
        entry1 = filestore.maplink(link, "root", "pypi", "pytest")
        entry1.file_set_content(b"")
        assert entry1.file_exists()
        entry1.file_delete()
        assert not entry1.file_exists()

    def test_maplink_egg(self, filestore, gen):
        link = gen.pypi_package_link("master#egg=pytest-dev", md5=False)
        entry1 = filestore.maplink(link, "root", "pypi", "pytest")
        entry2 = filestore.maplink(link, "root", "pypi", "pytest")
        assert entry1 == entry2
        assert not entry1 != entry2
        assert entry1.relpath.endswith("/master")
        assert entry1.eggfragment == "pytest-dev"
        assert entry1.version == "dev"
        assert not entry1.hash_spec
        assert entry1.url == link.url_nofrag
        assert entry2.eggfragment == "pytest-dev"
        assert entry2.version == "dev"

    def test_maplink_egg_version(self, filestore, gen):
        link = gen.pypi_package_link("master#egg=pytest-1.0", md5=False)
        entry1 = filestore.maplink(link, "root", "pypi", "pytest")
        assert entry1.version == '1.0'

    def test_maplink_egg_no_version(self, filestore, gen):
        link = gen.pypi_package_link("master#egg=pytest", md5=False)
        entry2 = filestore.maplink(link, "root", "pypi", "pytest")
        assert entry2.version == ''

    def test_relpathentry(self, filestore, gen):
        link = gen.pypi_package_link("pytest-1.7.zip", md5=False)
        entry = filestore.maplink(link, "root", "pypi", "pytest")
        assert entry.url == link.url
        assert not entry.file_exists()
        hash_type = "sha256"
        hash_value = getattr(hashlib, hash_type)(b"").hexdigest()
        entry.hash_spec = hash_spec = "%s=%s" %(hash_type, hash_value)
        assert not entry.file_exists()
        entry.file_set_content(b"")
        assert entry.file_exists()
        assert entry.url == link.url
        assert entry.hash_spec.endswith(hash_value)

        # reget
        entry = filestore.get_file_entry(entry.relpath)
        assert entry.file_exists()
        assert entry.url == link.url
        assert entry.hash_spec == hash_spec
        entry.delete()
        assert not entry.file_exists()

    def test_cache_remote_file(self, filestore, httpget, gen):
        link = gen.pypi_package_link("pytest-1.8.zip", md5=False)
        entry = filestore.maplink(link, "root", "pypi", "pytest")
        assert not entry.hash_spec and not entry.file_exists()
        filestore.keyfs.restart_as_write_transaction()
        headers={"content-length": "3",
                 "last-modified": "Thu, 25 Nov 2010 20:00:27 GMT",
        }
        httpget.url2response[link.url] = dict(status_code=200,
                headers=headers, raw = BytesIO(b"123"))
        for part in entry.iter_cache_remote_file():
            pass
        rheaders = entry.gethttpheaders()
        assert rheaders["content-length"] == "3"
        assert rheaders["content-type"] in zip_types
        assert rheaders["last-modified"] == headers["last-modified"]
        bytes = entry.file_get_content()
        assert bytes == b"123"

        # reget entry and check about content
        filestore.keyfs.restart_as_write_transaction()
        entry = filestore.get_file_entry(entry.relpath)
        assert entry.file_exists()
        assert entry.hash_value == getdigest(bytes, entry.hash_type)
        assert entry.file_size() == 3
        rheaders = entry.gethttpheaders()
        assert entry.file_get_content() == b"123"

    @pytest.mark.storage_with_filesystem
    @pytest.mark.parametrize("mode", ("commit", "rollback"))
    def test_file_tx(self, filestore, gen, mode):
        assert filestore.keyfs.tx
        link = gen.pypi_package_link("pytest-1.8.zip", md5=False)
        entry = filestore.maplink(link, "root", "pypi", "pytest")
        assert not entry.file_exists()
        entry.file_set_content(b'123')
        assert entry.file_exists()
        assert not filestore.storedir.join(entry.relpath).exists()
        assert entry.file_get_content() == b'123'
        if mode == "commit":
            filestore.keyfs.restart_as_write_transaction()
            assert filestore.storedir.join(entry.relpath).exists()
            entry.file_delete()
            assert filestore.storedir.join(entry.relpath).exists()
            assert not entry.file_exists()
            filestore.keyfs.commit_transaction_in_thread()
            assert not filestore.storedir.join(entry.relpath).exists()
        elif mode == "rollback":
            filestore.keyfs.rollback_transaction_in_thread()
            assert not filestore.storedir.join(entry.relpath).exists()

    def test_iterfile_remote_no_headers(self, filestore, httpget, gen):
        link = gen.pypi_package_link("pytest-1.8.zip", md5=False)
        entry = filestore.maplink(link, "root", "pypi", "pytest")
        assert not entry.hash_spec
        headers={}
        httpget.url2response[link.url] = dict(status_code=200,
                headers=headers, raw = BytesIO(b"123"))
        for part in entry.iter_cache_remote_file():
            pass
        rheaders = entry.gethttpheaders()
        assert rheaders["content-length"] == "3"
        assert rheaders["content-type"] in zip_types
        assert entry.file_get_content() == b"123"

    def test_iterfile_remote_error_size_mismatch(self, filestore, httpget, gen):
        link = gen.pypi_package_link("pytest-3.0.zip", md5=False)
        entry = filestore.maplink(link, "root", "pypi", "pytest")
        assert not entry.hash_spec
        headers={"content-length": "3",
                 "last-modified": "Thu, 25 Nov 2010 20:00:27 GMT",
                 "content-type": "application/zip"}
        httpget.url2response[link.url] = dict(status_code=200,
                headers=headers, raw = BytesIO(b"1"))
        with pytest.raises(ValueError):
            for part in entry.iter_cache_remote_file():
                pass

    def test_iterfile_remote_nosize(self, filestore, httpget, gen):
        link = gen.pypi_package_link("pytest-3.0.zip", md5=False)
        entry = filestore.maplink(link, "root", "pypi", "pytest")
        assert not entry.hash_spec
        headers={"last-modified": "Thu, 25 Nov 2010 20:00:27 GMT",
                 "content-length": None,}
        assert entry.file_size() is None
        httpget.url2response[link.url] = dict(status_code=200,
                headers=headers, raw=BytesIO(b"1"))
        for part in entry.iter_cache_remote_file():
            pass
        assert entry.file_get_content() == b"1"
        entry2 = filestore.get_file_entry(entry.relpath)
        assert entry2.file_size() == 1
        rheaders = entry.gethttpheaders()
        assert rheaders["last-modified"] == headers["last-modified"]
        assert rheaders["content-type"] in zip_types

    def test_iterfile_remote_error_md5(self, filestore, httpget, gen):
        link = gen.pypi_package_link("pytest-3.0.zip")
        entry = filestore.maplink(link, "root", "pypi", "pytest")
        assert entry.hash_spec and entry.hash_spec == link.hash_spec
        headers={"content-length": "3",
                 "last-modified": "Thu, 25 Nov 2010 20:00:27 GMT",
                 "content-type": "application/zip"}
        httpget.url2response[link.url_nofrag] = dict(status_code=200,
                headers=headers, raw=BytesIO(b"123"))
        with pytest.raises(ValueError) as excinfo:
            for part in entry.iter_cache_remote_file():
                pass
        assert link.md5 in str(excinfo.value)
        assert not entry.file_exists()

    @pytest.mark.notransaction
    def test_iterfile_eggfragment(self, filestore, httpget, gen):
        link = gen.pypi_package_link("master#egg=pytest-dev", md5=False)
        with filestore.keyfs.transaction(write=True):
            entry = filestore.maplink(link, "root", "pypi", "pytest")
        assert entry.eggfragment
        assert entry.url
        headers={"content-length": "4",
                 "last-modified": "Thu, 25 Nov 2010 20:00:27 GMT",
                 "content-type": "application/zip"}

        httpget.mockresponse(link.url_nofrag, headers=headers,
                             raw=BytesIO(b"1234"))
        for part in entry.iter_cache_remote_file():
            pass
        with filestore.keyfs.transaction(write=False):
            assert entry.file_get_content() == b"1234"
        httpget.mockresponse(entry.url, headers=headers, raw=BytesIO(b"3333"))
        for part in entry.iter_cache_remote_file():
            pass
        with filestore.keyfs.transaction(write=False):
            assert entry.file_get_content() == b"3333"

    def test_store_and_iter(self, filestore):
        content = b"hello"
        entry = filestore.store("user", "index", "something-1.0.zip", content)
        assert entry.hash_spec.endswith("="+getdigest(content, entry.hash_type))
        assert entry.file_exists()
        filestore.keyfs.restart_as_write_transaction()
        entry2 = filestore.get_file_entry(entry.relpath)
        assert entry2.basename == "something-1.0.zip"
        assert entry2.file_exists()
        assert entry2.hash_spec == entry.hash_spec
        assert entry2.last_modified
        assert entry2.file_get_content() == content

def test_maplink_nochange(filestore, gen):
    filestore.keyfs.restart_as_write_transaction()
    link = gen.pypi_package_link("pytest-1.2.zip")
    entry1 = filestore.maplink(link, "root", "pypi", "pytest")
    filestore.keyfs.commit_transaction_in_thread()
    last_serial = filestore.keyfs.get_current_serial()

    # start a new write transaction
    filestore.keyfs.begin_transaction_in_thread(write=True)
    entry2 = filestore.maplink(link, "root", "pypi", "pytest")
    assert entry1.relpath == entry2.relpath
    assert entry1.basename == entry2.basename == "pytest-1.2.zip"
    assert py.builtin._istext(entry1.hash_spec)
    filestore.keyfs.commit_transaction_in_thread()
    assert filestore.keyfs.get_current_serial() == last_serial
