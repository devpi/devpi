from contextlib import suppress
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler
from urllib.request import Request
from urllib.request import build_opener
import json
import pytest
import re


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def fetch(url, headers=None):
    if headers is None:
        headers = {}
    opener = build_opener(NoRedirect)
    req = Request(url, headers=headers)
    try:
        with opener.open(req) as f:
            data = f.read()
            if data:
                with suppress(json.JSONDecodeError):
                    f.json = json.loads(data)
            return f
    except HTTPError as e:
        return e


@pytest.mark.parametrize("headers, path, expected", [
    (
        {"Host": "outside3.com"}, "",
        "http://outside3.com"),
    (
        {"Host": "outside3.com:3141"}, "",
        "http://outside3.com:3141")])
def test_outside_url_nginx(headers, path, expected, nginx_host_port):
    (host, port) = nginx_host_port
    headers = dict((str(k), str(v)) for k, v in headers.items())
    r = fetch(f'http://{host}:{port}{path}/+api', headers=headers)
    assert r.json['result']['login'] == "%s/+login" % expected
    r = fetch(f'http://{host}:{port}{path}', headers=headers)
    assert r.status == 200


class TestWithOutsideURLHeader:
    @pytest.fixture(scope="class")
    def adjust_nginx_conf_content(self):
        def adjust_nginx_conf_content(content):
            return re.sub(
                'proxy_set_header X-outside-url.*$',
                'proxy_set_header X-outside-url $x_scheme://outside.com;',
                content,
                flags=re.I | re.M)
        return adjust_nginx_conf_content

    def test_outside_url_nginx(self, nginx_host_port):
        (host, port) = nginx_host_port
        r = fetch(f'http://{host}:{port}/+api')
        assert r.json['result']['login'] == "http://outside.com/+login"
        r = fetch(f'http://{host}:{port}')
        assert r.status == 200
        r = fetch(f'http://{host}:{port}/')
        assert r.status == 200


class TestWithOutsideURLSubPathHeader:
    @pytest.fixture(scope="class")
    def adjust_nginx_conf_content(self):
        def adjust_nginx_conf_content(content):
            return re.sub(
                'proxy_set_header X-outside-url.*$',
                'proxy_set_header X-outside-url $x_scheme://outside.com/foo;',
                content,
                flags=re.I | re.M)
        return adjust_nginx_conf_content

    def test_outside_url_nginx(self, nginx_host_port):
        (host, port) = nginx_host_port
        r = fetch(f'http://{host}:{port}/+api')
        assert r.json['result']['login'] == "http://outside.com/foo/+login"
        r = fetch(f'http://{host}:{port}/foo')
        assert r.status == 200
        r = fetch(f'http://{host}:{port}/foo/')
        assert r.status in (200, 302)
        # with devpi-web installed we get a redirect
        if r.status == 302:
            assert r.headers['location'] == 'http://outside.com/foo'
