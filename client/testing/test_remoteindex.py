
from devpi.remoteindex import RemoteIndex, LinkSet, parselinks
from devpi_common.s_url import DistURL
from devpi.use import Current

def test_linkset():
    links = parselinks("""
        <a href="http://something/pkg-1.2.tar.gz"/>
        <a href="http://something/pkg-1.2dev1.zip"/>
        <a href="http://something/pkg-1.2dev2.zip"/>
    """, "http://something")
    ls = LinkSet(links)
    link = ls.getnewestversion("pkg")
    assert DistURL(link.url).url_nofrag.endswith("pkg-1.2.tar.gz")

class TestRemoteIndex:
    def test_basic(self, monkeypatch, gen, tmpdir):
        md5 = gen.md5()
        indexurl = "http://my/simple/"
        current = Current(tmpdir.join("client"))
        current.reconfigure(dict(simpleindex=indexurl))
        ri = RemoteIndex(current)
        def mockget(url):
            assert url.startswith(indexurl)
            return """
                <a href="../../pkg-1.2.tar.gz#md5=%s"/>
                <a href="http://something/pkg-1.2dev1.zip"/>
                <a href="http://something/pkg-1.2dev2.zip"/>
            """ % md5
        monkeypatch.setattr(ri, "getcontent", mockget)
        link = ri.getbestlink("pkg")
        assert DistURL(link.url).url_nofrag == "http://my/pkg-1.2.tar.gz"

    def test_receive_error(self, monkeypatch, tmpdir):
        indexurl = "http://my/simple/"
        current = Current(tmpdir.join("client"))
        current.reconfigure(dict(simpleindex=indexurl))
        ri = RemoteIndex(current)
        def mockget(url):
            raise ri.ReceiveError(404)
        monkeypatch.setattr(ri, "getcontent", mockget)
        link = ri.getbestlink("pkg")
        assert link is None

def test_parselinks():
    content = """<html><a href="href" rel="rel">text</a></html>"""
    link = parselinks(content, "http://root")[0]
    assert link.url == "http://root/href"
