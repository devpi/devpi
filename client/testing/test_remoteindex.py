
from devpi.remoteindex import RemoteIndex, LinkSet
from devpi_common import c_url as urlutil
from devpi.use import Current

def test_linkset():
    links = urlutil.parselinks("""
        <a href="http://something/pkg-1.2.tar.gz"/>
        <a href="http://something/pkg-1.2dev1.zip"/>
        <a href="http://something/pkg-1.2dev2.zip"/>
    """)
    ls = LinkSet(links)
    assert ls.getnewestversion("pkg").href.endswith("pkg-1.2.tar.gz")

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
        assert link.href == "http://my/pkg-1.2.tar.gz"

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
