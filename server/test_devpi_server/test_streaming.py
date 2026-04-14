from __future__ import annotations

from time import sleep
import base64
import contextlib
import httpx
import pytest
import sys
import typing


if typing.TYPE_CHECKING:
    from testing.simpypi import SimPyPI
    import pathlib


pytestmark = [
    pytest.mark.skipif(
        sys.platform == "win32",
        reason="issues with process management on Windows"),
    pytest.mark.slow]


@pytest.fixture
def host_port(request, storage_info):
    if "storage_with_filesystem" not in storage_info.get("_test_markers", []):
        pytest.skip("The storage doesn't have marker 'storage_with_filesystem'.")
    return request.getfixturevalue("primary_host_port")


@pytest.fixture
def server_url_session(host_port, simpypi):
    with httpx.Client() as s:
        s.headers["Accept"] = "application/json"
        s.headers["Content-Type"] = "application/json"
        url = "http://%s:%s/" % host_port
        r = s.post(url + "+login", json={"user": "root", "password": ""}).json()
        auth = "%s:%s" % ("root", r["result"]["password"])
        s.headers["X-Devpi-Auth"] = base64.b64encode(auth.encode()).decode()
        existing = s.get(url).json()["result"]
        if "mirror" not in existing["root"]["indexes"]:
            indexconfig = dict(
                type="mirror", mirror_url=simpypi.simpleurl, mirror_cache_expiry=0
            )
            r = s.put(url + "root/mirror", json=indexconfig).json()
            assert r["type"] == "indexconfig"
            assert r["result"]["mirror_url"] == simpypi.simpleurl
        yield (url, s)


@pytest.fixture(scope="session")
def content_digest():
    import hashlib
    content = b'deadbeaf' * 128
    content = content + b'sandwich' * 128
    content = content * 512
    digest = hashlib.sha256(content).hexdigest()
    return (content, digest)


@pytest.fixture
def files_path(primary_server_path):
    return primary_server_path / '+files'


class TestStreaming(object):
    @pytest.mark.slow
    @pytest.mark.parametrize("length,pkg_version,pkg_name", [
        (None, '1.0', 'pkg1'), (False, '1.1', 'pkg2')])
    def test_streaming_download(self, content_digest, files_path, length, pkg_version, pkg_name, server_url_session, simpypi, storage_info):
        if "storage_with_filesystem" not in storage_info.get('_test_markers', []):
            pytest.skip("The storage doesn't have marker 'storage_with_filesystem'.")
        (content, digest) = content_digest
        (url, s) = server_url_session
        pkgzip = f"{pkg_name}-{pkg_version}.zip"
        simpypi.add_release(pkg_name, pkgver='%s#sha256=%s' % (pkgzip, digest))
        simpypi.add_file(
            f"/{pkg_name}/{pkgzip}", content, stream=True, length=length)
        with contextlib.closing(s.get(url + f"root/mirror/{pkg_name}")) as r:
            r = r.json()
        assert pkg_version in r['result'], r
        href = r['result'][pkg_version]['+links'][0]['href']
        with httpx.stream("get", href) as r:
            stream = r.iter_bytes(1024)
            data = next(stream)
            assert data == b'deadbeaf' * 128
            part = next(stream)
            assert part == b'sandwich' * 128
            data = data + part
            if length is not False:
                assert r.headers['content-length'] == str(len(content))
            for part in stream:
                data = data + part
            assert data == content
        pkg_file = files_path.joinpath(
            'root', 'mirror', '+f', digest[:3], digest[3:16], pkgzip)
        # this is sometimes delayed a bit, so we check for a while
        for i in range(50):
            if pkg_file.exists():
                break
            sleep(0.1)
        assert pkg_file.exists()

    @pytest.mark.parametrize("size_factor,pkg_version,pkg_name", [
        (2, '1.2', 'pkg3'), (0.5, '1.3', 'pkg4')])
    def test_streaming_differing_content_size(
        self,
        content_digest,
        files_path,
        pkg_version,
        pkg_name,
        server_url_session,
        simpypi,
        size_factor,
    ):
        (content, digest) = content_digest
        (url, s) = server_url_session
        pkgzip = f"{pkg_name}-{pkg_version}.zip"
        length = int(len(content) * size_factor)
        simpypi.add_release(pkg_name, pkgver='%s#sha256=%s' % (pkgzip, digest))
        simpypi.add_file(
            f"/{pkg_name}/{pkgzip}", content, stream=True, length=length)
        with contextlib.closing(s.get(url + f"root/mirror/{pkg_name}")) as _r:
            r = _r.json()
        assert pkg_version in r['result'], r
        href = r['result'][pkg_version]['+links'][0]['href']
        with httpx.stream("get", href) as r:
            stream = r.iter_bytes(1024)
            data = next(stream)
            assert data == b'deadbeaf' * 128
            part = next(stream)
            assert part == b'sandwich' * 128
            data = data + part
            assert r.headers['content-length'] == str(length)
            try:
                for part in stream:
                    data = data + part
            except httpx.RemoteProtocolError:
                pass
        pkg_file = files_path.joinpath(
            'root', 'pypi', '+f', digest[:3], digest[3:16], pkgzip)
        assert not pkg_file.exists()

    @pytest.mark.slow
    @pytest.mark.parametrize(
        "length,pkg_version,pkg_name,disconnect_at_length", [(None, "1.0", "pkg1", 10), (False, "1.1", "pkg2", -1025)]
    )
    def test_disconnect_while_streaming(
        self,
        content_digest: tuple[bytes, bytes],
        files_path: pathlib.Path,
        length: bool | None,  # noqa: FBT001
        pkg_version: str,
        pkg_name: str,
        server_url_session: tuple[str, httpx.Client],
        simpypi: SimPyPI,
        storage_info: dict,
        disconnect_at_length: int
    ):
        from time import sleep

        if "storage_with_filesystem" not in storage_info.get("_test_markers", []):
            pytest.skip("The storage doesn't have marker 'storage_with_filesystem'.")
        (content, digest) = content_digest
        (url, s) = server_url_session
        pkgzip = f"{pkg_name}-{pkg_version}.zip"
        simpypi.add_release(pkg_name, pkgver="%s#sha256=%s" % (pkgzip, digest))
        simpypi.add_file(f"/{pkg_name}/{pkgzip}", content, stream=True, length=length)
        with contextlib.closing(s.get(url + f"root/mirror/{pkg_name}")) as r:
            r = r.json()
        assert pkg_version in r["result"], r
        href = r["result"][pkg_version]["+links"][0]["href"]
        data = b''
        receive_bytes_len = 0
        disconnect_len = disconnect_at_length if disconnect_at_length > 0 else len(content) + disconnect_at_length
        with httpx.stream("get", href) as r:
            stream = r.iter_bytes(1024)
            while True:
                streaming_data = next(stream)
                data += streaming_data
                if len(data) >= disconnect_len:
                    break

        assert data != content

        pkg_file = files_path.joinpath(
            "root", "mirror", "+f", digest[:3], digest[3:16], pkgzip
        )
        # this is sometimes delayed a bit, so we check for a while
        for i in range(50):
            if pkg_file.exists():
                break
            sleep(0.1)
        assert pkg_file.exists()
