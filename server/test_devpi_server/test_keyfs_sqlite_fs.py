from devpi_server.keyfs_sqlite_fs import (
    commit_renames, make_rel_renames, check_pending_renames
)
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
        with pytest.raises(RuntimeError):
            with keyfs.transaction() as tx:
                tx.conn.io_file_set('foo', b'foo')
                tmppath = tx.conn.dirty_files[keyfs.basedir.join('foo').strpath].tmppath
                assert os.path.exists(tmppath)
                # abort transaction
                raise RuntimeError
        assert not os.path.exists(tmppath)
