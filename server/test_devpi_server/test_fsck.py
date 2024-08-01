from devpi_server.main import DATABASE_VERSION
from devpi_server.main import set_state_version
from pathlib import Path
import pytest
import subprocess


@pytest.mark.notransaction
@pytest.mark.storage_with_filesystem
def test_fsck_checksum_mismatch(mapp, storage_args):
    api = mapp.create_and_use()
    content = b'content'
    mapp.upload_file_pypi("hello-1.0.tar.gz", content, "hello", "1.0")
    with mapp.xom.keyfs.read_transaction():
        stage = mapp.xom.model.getstage(api.stagename)
        linkstore = stage.get_linkstore_perstage('hello', '1.0')
        (link,) = linkstore.get_links()
        path = Path(link.entry.file_os_path())
    set_state_version(mapp.xom.config, DATABASE_VERSION)
    proc = subprocess.run(
        [  # noqa: S603,S607 - testing only
            "devpi-fsck",
            "--serverdir", str(mapp.xom.config.server_path),
            *storage_args(mapp.xom.config.server_path)],
        check=False, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    assert proc.returncode == 0, proc.stdout.decode()
    path.write_bytes(b'foo')
    proc = subprocess.run(
        [  # noqa: S603,S607 - testing only
            "devpi-fsck",
            "--serverdir", str(mapp.xom.config.server_path),
            *storage_args(mapp.xom.config.server_path)],
        check=False, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    out = proc.stdout.decode()
    assert proc.returncode == 1, out
    assert 'ERROR' in out
    assert 'hello-1.0.tar.gz' in out
    assert 'mismatch, got' in out
