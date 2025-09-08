from devpi_server.filestore_fs import FSIOFile
from devpi_server.keyfs_types import FilePathInfo
from devpi_server.keyfs_types import RelPath
from functools import partial
from pathlib import Path
import os
import pytest


class TestRenameFileLogic:
    def test_new_content_nocrash(self, caplog, file_digest, tmpdir):
        hello_content = b"hello"
        hello_digest = file_digest(hello_content)
        this_content = b"this"
        this_digest = file_digest(this_content)
        file1 = tmpdir.join("+files", "file1").ensure()
        file1.write(hello_content)
        with FSIOFile(Path(tmpdir), {}) as fs:
            assert file1.check()
            assert file1.read_binary() == hello_content
            hello_path_info = FilePathInfo(RelPath("file1"), hello_digest)
            assert fs.os_path(hello_path_info) == str(file1)
            assert fs.get_content(hello_path_info) == hello_content
            this_path_info = FilePathInfo(RelPath("file1"), this_digest)
            fs.set_content(this_path_info, this_content)
            (rel_rename,) = list(fs.iter_rel_renames())
            file1_tmp = tmpdir.join(rel_rename)
            rel_parts = Path(rel_rename).parts
            assert rel_parts[0] == "+files"
            assert rel_parts[1].startswith("file1")
            assert rel_rename.endswith("-tmp")
            assert file1_tmp.exists()
        assert file1.check()
        assert file1.read_binary() == this_content
        assert not file1_tmp.exists()
        with FSIOFile(Path(tmpdir), {}) as fs:
            caplog.clear()
            fs.perform_crash_recovery(partial(iter, [rel_rename]), lambda _: [])
            assert not caplog.getrecords()
        assert file1.check()
        assert file1.read_binary() == this_content
        assert not file1_tmp.exists()

    def test_new_content_crash(self, caplog, file_digest, mock, monkeypatch, tmpdir):
        hello_content = b"hello"
        hello_digest = file_digest(hello_content)
        this_content = b"this"
        this_digest = file_digest(this_content)
        file1 = tmpdir.join("+files", "file1").ensure()
        file1.write(hello_content)
        with FSIOFile(Path(tmpdir), {}) as fs:
            assert file1.check()
            assert file1.read_binary() == hello_content
            hello_path_info = FilePathInfo(RelPath("file1"), hello_digest)
            assert fs.os_path(hello_path_info) == str(file1)
            assert fs.get_content(hello_path_info) == hello_content
            this_path_info = FilePathInfo(RelPath("file1"), this_digest)
            fs.set_content(this_path_info, this_content)
            (rel_rename,) = list(fs.iter_rel_renames())
            file1_tmp = tmpdir.join(rel_rename)
            rel_parts = Path(rel_rename).parts
            assert rel_parts[0] == "+files"
            assert rel_parts[1].startswith("file1")
            assert rel_rename.endswith("-tmp")
            assert file1_tmp.exists()
            # simulate a crash
            _commit = mock.Mock()
            monkeypatch.setattr(fs, "_commit", _commit)
        assert file1.read_binary() == hello_content
        assert file1_tmp.exists()
        with FSIOFile(Path(tmpdir), {}) as fs:
            caplog.clear()
            fs.perform_crash_recovery(partial(iter, [rel_rename]), lambda _: [])
            assert len(caplog.getrecords(".*completed.*file-commit.*")) == 1
        assert file1.check()
        assert file1.read_binary() == this_content
        assert not file1_tmp.exists()

    def test_remove_nocrash(self, caplog, file_digest, tmpdir):
        hello_content = b"hello"
        hello_digest = file_digest(hello_content)
        file1 = tmpdir.join("+files", "file1").ensure()
        file1.write(hello_content)
        with FSIOFile(Path(tmpdir), {}) as fs:
            assert file1.check()
            assert file1.read_binary() == hello_content
            hello_path_info = FilePathInfo(RelPath("file1"), hello_digest)
            assert fs.os_path(hello_path_info) == str(file1)
            assert fs.get_content(hello_path_info) == hello_content
            fs.delete(hello_path_info)
            (rel_rename,) = list(fs.iter_rel_renames())
            assert tmpdir.join(rel_rename) == str(file1)
            assert file1.exists()
        assert not file1.exists()
        with FSIOFile(Path(tmpdir), {}) as fs:
            caplog.clear()
            fs.perform_crash_recovery(partial(iter, [rel_rename]), lambda _: [])
            assert not caplog.getrecords()
        assert not file1.exists()

    def test_remove_crash(self, caplog, file_digest, mock, monkeypatch, tmpdir):
        hello_content = b"hello"
        hello_digest = file_digest(hello_content)
        file1 = tmpdir.join("+files", "file1").ensure()
        file1.write(hello_content)
        with FSIOFile(Path(tmpdir), {}) as fs:
            assert file1.check()
            assert file1.read_binary() == hello_content
            hello_path_info = FilePathInfo(RelPath("file1"), hello_digest)
            assert fs.os_path(hello_path_info) == str(file1)
            assert fs.get_content(hello_path_info) == hello_content
            fs.delete(hello_path_info)
            (rel_rename,) = list(fs.iter_rel_renames())
            assert tmpdir.join(rel_rename) == str(file1)
            assert file1.exists()
            # simulate a crash
            _commit = mock.Mock()
            monkeypatch.setattr(fs, "_commit", _commit)
        assert file1.exists()
        with FSIOFile(Path(tmpdir), {}) as fs:
            caplog.clear()
            fs.perform_crash_recovery(partial(iter, [rel_rename]), lambda _: [])
            assert len(caplog.getrecords(".*completed.*file-del.*")) == 1
        assert not file1.exists()

    @pytest.mark.storage_with_filesystem
    @pytest.mark.notransaction
    def test_dirty_files_removed_on_rollback(self, file_digest, keyfs):
        content = b"foo"
        content_hash = file_digest(content)
        with pytest.raises(RuntimeError), keyfs.read_transaction() as tx:  # noqa: PT012
            file_path_info = FilePathInfo(RelPath("foo"), content_hash)
            tx.io_file.set_content(file_path_info, content)
            tmppath = tx.io_file._dirty_files[file_path_info.relpath].path
            assert os.path.exists(tmppath)
            # abort transaction
            raise RuntimeError
        assert not os.path.exists(tmppath)

    @pytest.mark.storage_with_filesystem
    @pytest.mark.notransaction
    def test_finalize_init(self, caplog, makexom, mock, monkeypatch, tmp_path):
        from devpi_server.filestore import MutableFileEntry
        from devpi_server.filestore import get_hashes
        from devpi_server.filestore import make_splitdir

        _commit = mock.Mock()
        _commit.return_value = None
        monkeypatch.setattr(
            "devpi_server.filestore_fs_base.FSIOFileBase._commit", _commit
        )
        xom = makexom(opts=("--serverdir", str(tmp_path)))
        content = b"foo"
        hashes = get_hashes(content)
        with xom.keyfs.write_transaction() as tx:
            hashdir_a, hashdir_b = make_splitdir(hashes.get_default_spec())
            key = tx.keyfs.STAGEFILE(
                user="user",
                index="index",
                hashdir_a=hashdir_a,
                hashdir_b=hashdir_b,
                filename="foo.txt",
            )
            entry = MutableFileEntry(key)
            entry.file_set_content(content, hashes=hashes)
            path = Path(tx.io_file.os_path(entry.file_path_info))
            (rel_rename,) = tx.io_file.get_rel_renames()
        assert _commit.called
        # due to the monkeypatch above the file renames shouldn't be done yet
        assert not path.exists()
        assert xom.config.server_path.joinpath(rel_rename).exists()
        monkeypatch.undo()
        caplog.clear()
        xom = makexom(opts=("--serverdir", str(tmp_path)))
        # getting the keyfs attribute should call finalize_init
        assert xom.keyfs
        # which should perform the renames
        assert path.exists()
        assert not xom.config.server_path.joinpath(rel_rename).exists()
        assert len(caplog.getrecords(".*completed.*file-commit.*")) == 1
