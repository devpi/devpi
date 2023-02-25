from __future__ import unicode_literals
import hashlib
import posixpath
import pytest
from devpi_common.url import URL


class TestURL:
    def test_basename(self):
        d = URL("http://codespeak.net/basename")
        assert d.basename == "basename"
        d = URL("http://codespeak.net")
        assert not d.basename
        d = URL("http://codespeak.net/basename?foo=bar")
        assert d.basename == "basename"
        assert d.query == "foo=bar"
        d = URL("http://codespeak.net?foo=bar")
        assert not d.basename
        assert d.query == "foo=bar"

    def test_repr(self):
        d = URL("http://host.com/path")
        assert repr(d) == "URL('http://host.com/path')"
        d = URL("http://host.com/path?foo=bar")
        assert repr(d) == "URL('http://host.com/path?foo=bar')"
        assert d.query == "foo=bar"
        d = URL("http://foo:bar@host.com/path")
        assert repr(d) == "URL('http://foo:****@host.com/path')"

    def test_str(self):
        d = URL("http://foo:bar@host.com/path")
        assert str(d) == "http://foo:bar@host.com/path"

    def test_parentbasename(self):
        d = URL("http://codespeak.net/simple/basename/")
        assert d.parentbasename == "basename"
        assert d.basename == ""
        d = URL("http://codespeak.net/simple/basename/?foo=bar")
        assert d.parentbasename == "basename"
        assert d.basename == ""
        assert d.query == "foo=bar"

    def test_hashing(self):
        assert hash(URL("http://a")) == hash(URL("http://a"))
        assert URL("http://a") == URL("http://a")
        assert hash(URL("http://a?foo=bar")) == hash(URL("http://a?foo=bar"))
        assert URL("http://a?foo=bar") == URL("http://a?foo=bar")

    def test_eggfragment(self):
        url = URL("http://a/py.tar.gz#egg=py-dev")
        assert url.eggfragment == "py-dev"
        url = URL("http://a/py.tar.gz?foo=bar#egg=py-dev")
        assert url.eggfragment == "py-dev"
        assert url.query == "foo=bar"

    def test_md5(self):
        url = URL("http://a/py.tar.gz#md5=123123")
        assert url.md5 == "123123"
        assert url.hash_algo == hashlib.md5
        assert url.hash_type == "md5"
        assert url.hash_value == "123123"
        url = URL("http://a/py.tar.gz?foo=bar#md5=123123")
        assert url.md5 == "123123"
        assert url.hash_algo == hashlib.md5
        assert url.hash_type == "md5"
        assert url.hash_value == "123123"
        assert url.query == "foo=bar"

    @pytest.mark.parametrize("hashtype,hash_value", [
        ("sha256", "090123"),
        ("sha224", "1209380123"),
        ("md5", "102938")
    ])
    def test_hashtypes(self, hashtype, hash_value):
        link = URL('py-1.4.12.zip#%s=%s' % (hashtype, hash_value))
        assert link.hash_algo == getattr(hashlib, hashtype)
        assert link.hash_type == hashtype
        assert link.hash_value == hash_value
        link = URL('py-1.4.12.zip?foo=bar#%s=%s' % (hashtype, hash_value))
        assert link.hash_algo == getattr(hashlib, hashtype)
        assert link.hash_type == hashtype
        assert link.hash_value == hash_value
        assert link.query == "foo=bar"

    def test_nohashtypes(self):
        link = URL("whateveer#lqk=123")
        assert link.hash_value is None
        assert link.hash_algo is None
        assert link.hash_type is None
        link = URL("whateveer?foo=bar#lqk=123")
        assert link.hash_value is None
        assert link.hash_algo is None
        assert link.hash_type is None
        assert link.query == "foo=bar"

    @pytest.mark.parametrize("url,path,expected", [
        ("http://root", "dir1", "http://root/dir1"),
        ("http://root", "dir1/", "http://root/dir1/"),
        ("http://root/", "dir1/", "http://root/dir1/"),
        ("http://root/dir1", "dir2", "http://root/dir2"),
        ("http://root/dir1/", "dir2/", "http://root/dir1/dir2/"),
        ("http://root/dir1/", "/dir2", "http://root/dir2"),
        ("http://root/dir1/", "/dir2/", "http://root/dir2/"),
        ("http://root/dir1/dir3", "dir2", "http://root/dir1/dir2"),
        ("http://root/dir1/dir3/", "dir2/", "http://root/dir1/dir3/dir2/"),
        ("http://root/dir1/dir3/", "/dir2", "http://root/dir2"),
        ("http://root/dir1/dir3/", "/dir2/", "http://root/dir2/"),
        ("http://root?foo=bar", "dir1", "http://root/dir1?foo=bar"),
        ("http://root?foo=bar", "dir1/", "http://root/dir1/?foo=bar"),
        ("http://root/?foo=bar", "dir1/", "http://root/dir1/?foo=bar"),
        ("http://root/dir1?foo=bar", "dir2", "http://root/dir2?foo=bar"),
        ("http://root/dir1/?foo=bar", "dir2/", "http://root/dir1/dir2/?foo=bar"),
        ("http://root/dir1/?foo=bar", "/dir2", "http://root/dir2?foo=bar"),
        ("http://root/dir1/?foo=bar", "/dir2/", "http://root/dir2/?foo=bar"),
        ("http://root/dir1/dir3?foo=bar", "dir2", "http://root/dir1/dir2?foo=bar"),
        ("http://root/dir1/dir3/?foo=bar", "dir2/", "http://root/dir1/dir3/dir2/?foo=bar"),
        ("http://root/dir1/dir3/?foo=bar", "/dir2", "http://root/dir2?foo=bar"),
        ("http://root/dir1/dir3/?foo=bar", "/dir2/", "http://root/dir2/?foo=bar"),
    ])
    def test_joinpath(self, url, path, expected):
        d_url = URL(url)
        url_joined = d_url.joinpath(path).url
        assert url_joined == expected
        assert URL(url, path).url == expected

        if d_url.query:
            return

        assert d_url.joinpath(path, "end").url == expected.rstrip('/') + "/end"
        assert URL(url, path, "end").url == expected.rstrip('/') + "/end"

        assert d_url.joinpath(path, "end", asdir=1).url == expected.rstrip('/') + "/end/"
        assert URL(url, path, "end", asdir=1).url == expected.rstrip('/') + "/end/"

    def test_addpath(self):
        url = URL("http://root.com/path")
        assert url.addpath("sub").url == "http://root.com/path/sub"
        assert url.addpath("sub", asdir=1).url == "http://root.com/path/sub/"
        url = URL("http://root.com/path/")
        assert url.addpath("sub").url == "http://root.com/path/sub"
        assert url.addpath("sub", asdir=1).url == "http://root.com/path/sub/"
        url = URL("http://root.com/path?foo=bar")
        assert url.addpath("sub").url == "http://root.com/path/sub?foo=bar"
        assert url.addpath("sub", asdir=1).url == "http://root.com/path/sub/?foo=bar"
        url = URL("http://root.com/path/?foo=bar")
        assert url.addpath("sub").url == "http://root.com/path/sub?foo=bar"
        assert url.addpath("sub", asdir=1).url == "http://root.com/path/sub/?foo=bar"

    def test_instantiate_with_url(self):
        url = URL("http://hesie.de")
        assert URL(url) == url
        assert URL(url) is not url
        url = URL("http://hesie.de?foo=bar")
        assert URL(url) == url
        assert URL(url) is not url

    def test_empty_url(self):
        assert not URL("")
        assert not URL()
        url = URL(None)
        assert url.url == ""

    def test_asdir(self):
        assert URL("http://heise.de").asdir().url == "http://heise.de/"
        assert URL("http://py.org/path").asdir().url == "http://py.org/path/"
        assert URL("http://py.org/path/").asdir().url == "http://py.org/path/"
        assert URL("http://heise.de?foo=bar").asdir().url == "http://heise.de/?foo=bar"
        assert URL("http://py.org/path?foo=bar").asdir().url == "http://py.org/path/?foo=bar"
        assert URL("http://py.org/path/?foo=bar").asdir().url == "http://py.org/path/?foo=bar"

    def test_asfile(self):
        assert URL("http://heise.de").asfile().url == "http://heise.de"
        assert URL("http://heise.de/").asfile().url == "http://heise.de"
        assert URL("http://x.de/path/").asfile().url == "http://x.de/path"
        assert URL("http://x.de/path").asfile().url == "http://x.de/path"
        assert URL("http://heise.de?foo=bar").asfile().url == "http://heise.de?foo=bar"
        assert URL("http://heise.de/?foo=bar").asfile().url == "http://heise.de?foo=bar"
        assert URL("http://x.de/path/?foo=bar").asfile().url == "http://x.de/path?foo=bar"
        assert URL("http://x.de/path?foo=bar").asfile().url == "http://x.de/path?foo=bar"

    def test_joinpath_asdir(self):
        url = URL("http://heise.de")
        new = url.joinpath("hello", asdir=1)
        assert new.url == "http://heise.de/hello/"
        new = url.joinpath("hello/", asdir=1)
        assert new.url == "http://heise.de/hello/"
        url = URL("http://heise.de?foo=bar")
        new = url.joinpath("hello", asdir=1)
        assert new.url == "http://heise.de/hello/?foo=bar"
        new = url.joinpath("hello/", asdir=1)
        assert new.url == "http://heise.de/hello/?foo=bar"

    def test_geturl_nofrag(self):
        url = URL("http://a/py.tar.gz#egg=py-dev")
        assert url.geturl_nofragment() == "http://a/py.tar.gz"
        url = URL("http://a/py.tar.gz?foo=bar#egg=py-dev")
        assert url.geturl_nofragment() == "http://a/py.tar.gz?foo=bar"

    def test_url_nofrag(self):
        url = URL("http://a/py.tar.gz#egg=py-dev")
        res = url.url_nofrag
        assert not isinstance(res, URL)
        assert res == "http://a/py.tar.gz"
        url = URL("http://a/py.tar.gz?foo=bar#egg=py-dev")
        res = url.url_nofrag
        assert not isinstance(res, URL)
        assert res == "http://a/py.tar.gz?foo=bar"

    @pytest.mark.parametrize("url,path,expected", [
        ("/something/this", "/something/that", "that"),
        ("/something/this", "/something/that/", "that/"),
        ("/something/this", "/something/this", "this"),
        ("/something/this", "/something/this/", "this/"),
        ("/something/this", "/", "../"),
        ("/", "/this/that/", "this/that/"),
        ("/something/this/", "/something/that", "../that"),
        ("/something/this/", "/other/that", "../../other/that"),
        ("/something/this/", "/other/that", "../../other/that"),
        ("/something/this/", "/something/this/that", "that"),
        ("/something/this/", "/something/this/that/there", "that/there"),
    ])
    def test_relpath(self, url, path, expected):
        test_url = URL("http://example.com" + url)
        relpath = test_url.relpath(path)
        assert relpath == expected
        test_url = URL("http://example.com" + url + "foo=bar")
        relpath = test_url.relpath(path)
        assert relpath == expected

    def test_relpath_edge_case(self):
        with pytest.raises(ValueError):
            URL("http://qwe/path").relpath("lkjqwe")

    def test_netloc(self):
        assert URL("http://qwe/").netloc == 'qwe'
        assert URL("http://foo:pass@qwe/").netloc == 'foo:pass@qwe'
        assert URL("http://qwe/?foo=bar").netloc == 'qwe'
        assert URL("http://foo:pass@qwe/?foo=bar").netloc == 'foo:pass@qwe'

    def test_replace(self):
        url = URL("http://qwe/foo?bar=ham#hash")
        assert url.replace(scheme='https').url == "https://qwe/foo?bar=ham#hash"
        assert url.replace(scheme='').url == "//qwe/foo?bar=ham#hash"
        assert url.replace(netloc='world').url == "http://world/foo?bar=ham#hash"
        assert url.replace(netloc='').url == "http:///foo?bar=ham#hash"
        assert url.replace(path='/').url == "http://qwe/?bar=ham#hash"
        assert url.replace(path='').url == "http://qwe?bar=ham#hash"
        assert url.replace(query='').url == "http://qwe/foo#hash"
        assert url.replace(query='foo=bar').url == "http://qwe/foo?foo=bar#hash"
        assert url.replace(fragment='').url == "http://qwe/foo?bar=ham"
        assert url.replace(fragment='foo').url == "http://qwe/foo?bar=ham#foo"
        # original shouldn't have changed
        assert url.url == "http://qwe/foo?bar=ham#hash"
        # trying to change something not existing does nothing
        assert url.replace(foo='https').url == "http://qwe/foo?bar=ham#hash"

    def test_replace_netloc_parts(self):
        url = URL("http://example.com")
        assert url.replace(username="foo").url == "http://foo@example.com"
        assert url.replace(password="foo").url == "http://:foo@example.com"
        assert url.replace(hostname="foo").url == "http://foo"
        assert url.replace(port="8080").url == "http://example.com:8080"
        # original shouldn't have changed
        assert url.url == "http://example.com"
        url = URL("http://bar@example.com")
        assert url.replace(username="foo").url == "http://foo@example.com"
        assert url.replace(password="foo").url == "http://bar:foo@example.com"
        assert url.replace(hostname="foo").url == "http://bar@foo"
        assert url.replace(port="8080").url == "http://bar@example.com:8080"
        # original shouldn't have changed
        assert url.url == "http://bar@example.com"
        url = URL("http://bar:secret@example.com")
        assert url.replace(username="foo").url == "http://foo:secret@example.com"
        assert url.replace(password="foo").url == "http://bar:foo@example.com"
        assert url.replace(hostname="foo").url == "http://bar:secret@foo"
        assert url.replace(port="8080").url == "http://bar:secret@example.com:8080"
        # original shouldn't have changed
        assert url.url == "http://bar:secret@example.com"
        url = URL("http://example.com:8080")
        assert url.replace(username="foo").url == "http://foo@example.com:8080"
        assert url.replace(password="foo").url == "http://:foo@example.com:8080"
        assert url.replace(hostname="foo").url == "http://foo:8080"
        assert url.replace(port="1234").url == "http://example.com:1234"
        # original shouldn't have changed
        assert url.url == "http://example.com:8080"
        url = URL("http://bar:secret@example.com:8080")
        assert url.replace(username=None).url == "http://:secret@example.com:8080"
        assert url.replace(password=None).url == "http://bar@example.com:8080"
        with pytest.raises(ValueError):
            url.replace(hostname=None)
        assert url.replace(port=None).url == "http://bar:secret@example.com"
        with pytest.raises(ValueError):
            url.replace(hostname="foo", netloc="bar")
        # original shouldn't have changed
        assert url.url == "http://bar:secret@example.com:8080"

    def test_replace_nothing(self):
        url = URL("http://qwe/foo?bar=ham#hash")
        new_url = url.replace()
        assert new_url is not url
        assert new_url.url == url.url

    def test_comparison(self):
        base = URL('https://pypi.org')
        url = URL('https://pypi.org/simple/foo').replace(path='')
        assert base == url
        assert not (base != url)  # noqa: SIM202 - we want to check __ne__

    def test_username(self):
        assert URL('http://example.com').username is None
        assert URL('http://user@example.com').username == 'user'
        assert URL('http://user:password@example.com').username == 'user'
        assert URL('https://example.com:443').username is None
        assert URL('https://user@example.com:443').username == 'user'
        assert URL('https://user:password@example.com:443').username == 'user'
        assert URL('https://user:password@example.com:443?foo=bar').username == 'user'

    def test_password(self):
        assert URL('http://example.com').password is None
        assert URL('http://user@example.com').password is None
        assert URL('http://user:password@example.com').password == 'password'
        assert URL('https://example.com:443').password is None
        assert URL('https://user@example.com:443').password is None
        assert URL('https://user:password@example.com:443').password == 'password'
        assert URL('https://user:password@example.com:443?foo=bar').password == 'password'

    def test_hostname(self):
        assert URL('http://example.com').hostname == 'example.com'
        assert URL('http://example.com?foo=bar').hostname == 'example.com'
        assert URL('http://user@example.com').hostname == 'example.com'
        assert URL('http://user:password@example.com').hostname == 'example.com'
        assert URL('https://example.com:443').hostname == 'example.com'
        assert URL('https://user@example.com:443').hostname == 'example.com'
        assert URL('https://user:password@example.com:443').hostname == 'example.com'

    def test_port(self):
        assert URL('http://example.com').port is None
        assert URL('http://example.com?foo=bar').port is None
        assert URL('http://user@example.com').port is None
        assert URL('http://user:password@example.com').port is None
        assert URL('https://example.com:443').port == 443
        assert URL('https://example.com:443?foo=bar').port == 443
        assert URL('https://user@example.com:443').port == 443
        assert URL('https://user:password@example.com:443').port == 443

    def test_query(self):
        assert URL("http://example.com").query == ""
        assert URL("http://example.com?foo=bar").query == "foo=bar"

    @pytest.mark.parametrize("url,kwargs,expected", [
        ("http://example.com", dict(), dict()),
        ("http://example.com?foo=bar", dict(), dict(foo=["bar"])),
        ("http://example.com?foo=ham&foo=bar", dict(), dict(foo=["ham", "bar"])),
        ("http://example.com?foo=ham&foo=bar&bar=", dict(), dict(foo=["ham", "bar"])),
        ("http://example.com?foo=ham&foo=bar&bar=", dict(keep_blank_values=True), dict(foo=["ham", "bar"], bar=[""])),
    ])
    def test_query_dict(self, url, kwargs, expected):
        assert URL(url).get_query_dict(**kwargs) == expected

    @pytest.mark.parametrize("url,kwargs,expected", [
        ("http://example.com", dict(), []),
        ("http://example.com?foo=bar", dict(), [("foo", "bar")]),
        ("http://example.com?foo=ham&foo=bar", dict(), [("foo", "ham"), ("foo", "bar")]),
        ("http://example.com?foo=ham&foo=bar&bar=", dict(), [("foo", "ham"), ("foo", "bar")]),
        ("http://example.com?foo=ham&foo=bar&bar=", dict(keep_blank_values=True), [("foo", "ham"), ("foo", "bar"), ("bar", "")]),
    ])
    def test_query_items(self, url, kwargs, expected):
        assert URL(url).get_query_items(**kwargs) == expected

    @pytest.mark.parametrize("url,query,expected", [
        ("http://example.com", "foo=bar", "http://example.com?foo=bar"),
        ("http://example.com", [("foo", "bar")], "http://example.com?foo=bar"),
        ("http://example.com", dict(foo="bar"), "http://example.com?foo=bar"),
        ("http://example.com?foo=ham", "foo=bar", "http://example.com?foo=bar"),
        ("http://example.com?foo=ham", [("foo", "bar")], "http://example.com?foo=bar"),
        ("http://example.com?foo=ham", dict(foo="bar"), "http://example.com?foo=bar"),
    ])
    def test_query_replace(self, url, query, expected):
        assert URL(url).replace(query=query) == expected


#
# test torelpath/fromrelpath
#

@pytest.mark.parametrize("url", [
    "http://codespeak.net", "https://codespeak.net",
    "http://codespeak.net/path",
    "http://codespeak.net:3123/path",
    "https://codespeak.net:80/path",
])
def test_canonical_url_path_mappings(url):
    url = URL(url)
    path = url.torelpath()
    assert path[0] != "/"
    assert posixpath.normpath(path) == path
    back_url = URL.fromrelpath(path)
    assert url == back_url
