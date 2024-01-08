import base64
import contextlib
import json
import pytest
import requests
import sys


pytestmark = [
    pytest.mark.skipif(
        sys.platform == "win32",
        reason="issues with process management on Windows"),
    pytest.mark.skipif("not config.option.slow")]


@pytest.fixture
def host_port(master_host_port):
    return master_host_port


@pytest.fixture
def server_url_session(host_port, simpypi):
    s = requests.Session()
    s.headers = {'Accept': 'application/json', 'Content-Type': 'application/json'}
    url = 'http://%s:%s/' % host_port
    r = s.post(url + '+login', json.dumps({'user': 'root', 'password': ''})).json()
    auth = '%s:%s' % ('root', r['result']['password'])
    s.headers['X-Devpi-Auth'] = base64.b64encode(auth.encode('utf-8'))
    existing = s.get(url).json()['result']
    if 'mirror' not in existing['root']['indexes']:
        indexconfig = dict(
            type="mirror",
            mirror_url=simpypi.simpleurl,
            mirror_cache_expiry=0)
        r = s.put(url + 'root/mirror', json.dumps(indexconfig)).json()
        assert r['type'] == 'indexconfig'
        assert r['result']['mirror_url'] == simpypi.simpleurl
    yield (url, s)
    s.close()


@pytest.fixture(scope="session")
def content_digest():
    import hashlib
    content = b'deadbeaf' * 128
    content = content + b'sandwich' * 128
    content = content * 512
    digest = hashlib.sha256(content).hexdigest()
    return (content, digest)


@pytest.fixture
def files_directory(server_directory):
    return server_directory.join('master', '+files')


class TestStreaming(object):
    @pytest.mark.parametrize("length,pkg_version,pkg_name", [
        (None, '1.0', 'pkg1'), (False, '1.1', 'pkg2')])
    def test_streaming_download(self, content_digest, files_directory, length, pkg_version, pkg_name, server_url_session, simpypi, storage_info):
        from time import sleep
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
        r = requests.get(href, stream=True)
        with contextlib.closing(r):
            stream = r.iter_content(1024)
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
        pkg_file = files_directory.join(
            'root', 'mirror', '+f', digest[:3], digest[3:16], pkgzip)
        # this is sometimes delayed a bit, so we check for a while
        for i in range(50):
            if pkg_file.exists():
                break
            sleep(0.1)
        assert pkg_file.exists()

    @pytest.mark.parametrize("size_factor,pkg_version,pkg_name", [
        (2, '1.2', 'pkg3'), (0.5, '1.3', 'pkg4')])
    def test_streaming_differing_content_size(self, content_digest, files_directory, pkg_version, pkg_name, server_url_session, simpypi, size_factor, storage_info):
        if "storage_with_filesystem" not in storage_info.get('_test_markers', []):
            pytest.skip("The storage doesn't have marker 'storage_with_filesystem'.")
        (content, digest) = content_digest
        (url, s) = server_url_session
        pkgzip = f"{pkg_name}-{pkg_version}.zip"
        length = int(len(content) * size_factor)
        simpypi.add_release(pkg_name, pkgver='%s#sha256=%s' % (pkgzip, digest))
        simpypi.add_file(
            f"/{pkg_name}/{pkgzip}", content, stream=True, length=length)
        with contextlib.closing(s.get(url + f"root/mirror/{pkg_name}")) as r:
            r = r.json()
        assert pkg_version in r['result'], r
        href = r['result'][pkg_version]['+links'][0]['href']
        r = requests.get(href, stream=True)
        with contextlib.closing(r):
            stream = r.iter_content(1024)
            data = next(stream)
            assert data == b'deadbeaf' * 128
            part = next(stream)
            assert part == b'sandwich' * 128
            data = data + part
            assert r.headers['content-length'] == str(length)
            for part in stream:
                data = data + part
            assert data == content[:length]
        pkg_file = files_directory.join(
            'root', 'pypi', '+f', digest[:3], digest[3:16], pkgzip)
        assert not pkg_file.exists()
