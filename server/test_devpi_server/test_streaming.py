import base64
import json
import pytest
import requests


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
    return (url, s)


@pytest.fixture(scope="session")
def content_digest():
    import hashlib
    content = b'deadbeaf' * 1024
    content = content + b'cafe' * 1024
    digest = hashlib.sha256(content).hexdigest()
    return (content, digest)


@pytest.fixture
def files_directory(server_directory):
    return server_directory.join('master', '+files')


def test_streaming_download(content_digest, files_directory, server_url_session, simpypi):
    (content, digest) = content_digest
    (url, s) = server_url_session
    simpypi.add_release('pkg', pkgver='pkg-1.0.zip#sha256=%s' % digest)
    simpypi.add_file('/pkg/pkg-1.0.zip', content, stream=True)
    r = s.get(url + 'root/mirror/pkg').json()
    href = r['result']['1.0']['+links'][0]['href']
    r = requests.get(href, stream=True)
    stream = r.iter_content(8)
    data = next(stream)
    assert data == b'deadbeaf'
    assert r.headers['content-length'] == str(len(content))
    for part in stream:
        data = data + part
    assert data == content
    pkg_file = files_directory.join(
        'root', 'pypi', '+f', digest[:3], digest[3:16], 'pkg-1.0.zip')
    assert pkg_file.exists()


def test_streaming_no_content_size(content_digest, files_directory, server_url_session, simpypi):
    (content, digest) = content_digest
    (url, s) = server_url_session
    simpypi.add_release('pkg', pkgver='pkg-1.1.zip#sha256=%s' % digest)
    simpypi.add_file('/pkg/pkg-1.1.zip', content, stream=True, length=False)
    r = s.get(url + 'root/mirror/pkg').json()
    href = r['result']['1.1']['+links'][0]['href']
    r = requests.get(href, stream=True)
    stream = r.iter_content(8)
    data = next(stream)
    # assert data == b'deadbeaf'
    # assert r.headers['content-length'] == str(len(content))
    for part in stream:
        data = data + part
    assert data == content
    pkg_file = files_directory.join(
        'root', 'pypi', '+f', digest[:3], digest[3:16], 'pkg-1.1.zip')
    assert pkg_file.exists()


def test_streaming_too_big_content_size(content_digest, files_directory, server_url_session, simpypi):
    (content, digest) = content_digest
    (url, s) = server_url_session
    simpypi.add_release('pkg', pkgver='pkg-1.2.zip#sha256=%s' % digest)
    simpypi.add_file('/pkg/pkg-1.2.zip', content, stream=True, length=len(content) * 2)
    r = s.get(url + 'root/mirror/pkg').json()
    href = r['result']['1.2']['+links'][0]['href']
    r = requests.get(href, stream=True)
    stream = r.iter_content(8)
    data = next(stream)
    assert data == b'deadbeaf'
    assert r.headers['content-length'] == str(len(content) * 2)
    for part in stream:
        data = data + part
    assert data == content
    pkg_file = files_directory.join(
        'root', 'pypi', '+f', digest[:3], digest[3:16], 'pkg-1.2.zip')
    assert not pkg_file.exists()


def test_streaming_too_small_content_size(content_digest, files_directory, server_url_session, simpypi):
    (content, digest) = content_digest
    (url, s) = server_url_session
    simpypi.add_release('pkg', pkgver='pkg-1.3.zip#sha256=%s' % digest)
    simpypi.add_file('/pkg/pkg-1.3.zip', content, stream=True, length=len(content) // 2)
    r = s.get(url + 'root/mirror/pkg').json()
    href = r['result']['1.3']['+links'][0]['href']
    r = requests.get(href, stream=True)
    stream = r.iter_content(8)
    data = next(stream)
    assert data == b'deadbeaf'
    assert r.headers['content-length'] == str(len(content) // 2)
    for part in stream:
        data = data + part
    assert data == content[:len(content) // 2]
    pkg_file = files_directory.join(
        'root', 'pypi', '+f', digest[:3], digest[3:16], 'pkg-1.3.zip')
    assert not pkg_file.exists()
