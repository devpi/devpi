from devpi_server.filestore_fs import check_pending_renames
from devpi_server.filestore_fs import commit_renames
from devpi_server.filestore_fs import make_rel_renames
from devpi_server.keyfs_types import FilePathInfo
from pathlib import Path
import os
import pytest


class TestRenameFileLogic:
    def test_new_content_nocrash(self, tmpdir):
        file1 = tmpdir.join("file1")
        file1_tmp = file1 + "-tmp"
        file1.write("hello")
        file1_tmp.write("this")
        pending_renames = [(str(file1_tmp), str(file1))]
        rel_renames = make_rel_renames(str(tmpdir), pending_renames)
        commit_renames(str(tmpdir), rel_renames)
        assert file1.check()
        assert file1.read() == "this"
        assert not file1_tmp.exists()
        check_pending_renames(str(tmpdir), rel_renames)
        assert file1.check()
        assert file1.read() == "this"
        assert not file1_tmp.exists()

    def test_new_content_crash(self, tmpdir, caplog):
        file1 = tmpdir.join("file1")
        file1_tmp = file1 + "-tmp"
        file1.write("hello")
        file1_tmp.write("this")
        pending_renames = [(str(file1_tmp), str(file1))]
        rel_renames = make_rel_renames(str(tmpdir), pending_renames)
        # we don't call perform_pending_renames, simulating a crash
        assert file1.read() == "hello"
        assert file1_tmp.exists()
        check_pending_renames(str(tmpdir), rel_renames)
        assert file1.check()
        assert file1.read() == "this"
        assert not file1_tmp.exists()
        assert len(caplog.getrecords(".*completed.*file-commit.*")) == 1

    def test_remove_nocrash(self, tmpdir):
        file1 = tmpdir.join("file1")
        file1.write("hello")
        pending_renames = [(None, str(file1))]
        rel_renames = make_rel_renames(str(tmpdir), pending_renames)
        commit_renames(str(tmpdir), rel_renames)
        assert not file1.exists()
        check_pending_renames(str(tmpdir), rel_renames)
        assert not file1.exists()

    def test_remove_crash(self, tmpdir, caplog):
        file1 = tmpdir.join("file1")
        file1.write("hello")
        pending_renames = [(None, str(file1))]
        rel_renames = make_rel_renames(str(tmpdir), pending_renames)
        # we don't call perform_pending_renames, simulating a crash
        assert file1.exists()
        check_pending_renames(str(tmpdir), rel_renames)
        assert not file1.exists()
        assert len(caplog.getrecords(".*completed.*file-del.*")) == 1

    @pytest.mark.storage_with_filesystem
    @pytest.mark.notransaction
    def test_dirty_files_removed_on_rollback(self, keyfs):
        with pytest.raises(RuntimeError), keyfs.read_transaction() as tx:  # noqa: PT012
            tx.io_file.set_content(FilePathInfo("foo"), b"foo")
            tmppath = tx.io_file._dirty_files[str(keyfs.base_path / "foo")].tmppath
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

        _commit_renames = mock.Mock()
        _commit_renames.return_value = ([], [])
        monkeypatch.setattr(
            "devpi_server.keyfs_sqlite_fs.commit_renames", _commit_renames
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
        assert _commit_renames.called
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
