import pytest
from devpi.remoteindex import RemoteIndex, LinkSet, parselinks
from devpi_common.url import URL
from devpi.use import Current


def test_linkset():
    links = parselinks("""
        <a href="http://something/pkg-1.2.tar.gz"/>
        <a href="http://something/pkg-1.2dev1.zip"/>
        <a href="http://something/pkg-1.2dev2.zip"/>
    """, "http://something")
    ls = LinkSet(links)
    link = ls.getnewestversion("pkg")
    assert URL(link.url).basename == "pkg-1.2.tar.gz"


def test_linkset_underscore():
    links = parselinks("""
        <a href="http://something/pkg_foo-1.2.tar.gz"/>
        <a href="http://something/pkg_foo-1.2dev1.zip"/>
        <a href="http://something/pkg_foo-1.2dev2.zip"/>
    """, "http://something")
    ls = LinkSet(links)
    link = ls.getnewestversion("pkg_foo")
    assert URL(link.url).basename == "pkg_foo-1.2.tar.gz"


class TestRemoteIndex:
    def test_basic(self, monkeypatch, gen):
        md5 = gen.md5()
        indexurl = "http://my/simple/"
        current = Current()
        current.reconfigure(dict(simpleindex=indexurl))
        ri = RemoteIndex(current)
        def mockget(url):
            assert url.startswith(indexurl)
            return url, """
                <a href="../../pkg-1.2.tar.gz#md5=%s"/>
                <a href="http://something/pkg-1.2dev1.zip"/>
                <a href="http://something/pkg-1.2dev2.zip"/>
            """ % md5
        monkeypatch.setattr(ri, "getcontent", mockget)
        link = ri.getbestlink("pkg")
        assert URL(link.url).url_nofrag == "http://my/pkg-1.2.tar.gz"

    def test_receive_error(self, monkeypatch):
        indexurl = "http://my/simple/"
        current = Current()
        current.reconfigure(dict(simpleindex=indexurl))
        ri = RemoteIndex(current)
        def mockget(url):
            raise ri.ReceiveError(404)
        monkeypatch.setattr(ri, "getcontent", mockget)
        link = ri.getbestlink("pkg")
        assert link is None

    @pytest.mark.parametrize("specs,link", [
        ("pkg==0.2.8", "http://my/pkg-0.2.8.tar.gz"),
        ("pkg<=0.2.8", "http://my/pkg-0.2.8.tar.gz"),
        ("pkg<0.3", "http://my/pkg-0.2.8.tar.gz"),
        ("pkg!=0.3", "http://my/pkg-0.2.8.tar.gz"),
        ("pkg>0.2.8", "http://my/pkg-0.3.tar.gz"),
        ("pkg>=0.2.8", "http://my/pkg-0.3.tar.gz"),
        ("pkg<0.2.4,>0.2.2", "http://my/pkg-0.2.3.tar.gz"),
    ])
    def test_package_with_version_specs(self, monkeypatch, specs, link):
        indexurl = "http://my/simple/"
        current = Current()
        current.reconfigure(dict(simpleindex=indexurl))
        ri = RemoteIndex(current)
        def mockget(url):
            assert url.startswith(indexurl)
            assert url.endswith("pkg/")
            return url, """
                <a href="http://my/pkg-0.3.tar.gz"/>
                <a href="http://my/pkg-0.2.8.tar.gz"/>
                <a href="http://my/pkg-0.2.7.tar.gz"/>
                <a href="http://my/pkg-0.2.6.tar.gz"/>
                <a href="http://my/pkg-0.2.5.tar.gz"/>
                <a href="http://my/pkg-0.2.5a1.tar.gz"/>
                <a href="http://my/pkg-0.2.4.1.tar.gz"/>
                <a href="http://my/pkg-0.2.4.tar.gz"/>
                <a href="http://my/pkg-0.2.3.tar.gz"/>
                <a href="http://my/pkg-0.2.2.tar.gz"/>
                <a href="http://my/pkg-0.2.1.tar.gz"/>
                <a href="http://my/pkg-0.2.0.tar.gz"/>
            """
        monkeypatch.setattr(ri, "getcontent", mockget)
        lnk = ri.getbestlink(specs)
        assert URL(lnk.url).url_nofrag == link

def test_parselinks():
    content = """<html><a href="href" rel="rel">text</a></html>"""
    link = parselinks(content, "http://root")[0]
    assert link.url == "http://root/href"
