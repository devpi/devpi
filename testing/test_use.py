
import urllib
import pytest
import py
from devpi import use
from devpi import log
from devpi.main import Hub

class TestUnit:
    def test_write_and_read(self, tmpdir):
        api = use.Config(pypisubmit="/post", pushrelease="/push",
                        simpleindex="/index",
                        indexadmin="/indexadmin",
                        resultlog="/", upstreamurl="http://upstream",
                        path=tmpdir)
        api.save()
        newapi = use.Config()
        newapi.configure_frompath(tmpdir)
        assert newapi.pypisubmit == api.pypisubmit
        assert newapi.simpleindex == api.simpleindex
        assert newapi.resultlog == api.resultlog
        assert newapi.upstreamurl == api.upstreamurl
        assert newapi.venvdir == api.venvdir
        assert newapi.indexadmin == api.indexadmin

    def test_normalize_url(self, tmpdir):
        config = use.Config(simpleindex="http://my.serv/index1")
        url = config._normalize_url("index2")
        assert url == "http://my.serv/index2/"

    def test_empty_read(self, tmpdir):
        res = use.Config()
        res.configure_frompath(tmpdir)
        assert res.path is None

    def test_main(self, tmpdir, monkeypatch):
        monkeypatch.chdir(tmpdir)
        class args:
            delete = False
            indexurl = ["http://world/this"]
        api = dict(pypisubmit="/post", pushrelease="/push",
                   simpleindex="/index/",
                   resultlog="/resultlog/",
                   upstreamurl="http://upstream.com/")
        def urlopen(url):
            assert url == "http://world/this/-api"
            return py.io.BytesIO(py.std.json.dumps(api))

        monkeypatch.setattr(urllib, "urlopen", urlopen)
        use.main(Hub(debug=True), args)
        newapi = use.Config.from_path(tmpdir)
        assert newapi is not None
        assert newapi.pypisubmit == "http://world/post"
        assert newapi.pushrelease == "http://world/push"
        assert newapi.simpleindex == "http://world/index/"
        assert newapi.resultlog == "http://world/resultlog/"
        assert newapi.upstreamurl == "http://upstream.com/"
        assert newapi.venvdir == None

        # delete it
        class args_delete:
            indexurl = None
            delete = True
        use.main(Hub(debug=True), args_delete)
        newapi = use.Config()
        newapi.configure_frompath(tmpdir)
        assert newapi.path is None

    def test_main_venvsetting(self, create_venv, tmpdir, monkeypatch):
        venvdir = create_venv()
        monkeypatch.chdir(tmpdir)
        class args:
            delete = False
            indexurl = ["venv=%s" % venvdir]
        use.main(Hub(), args)
        config = use.Config.from_path()
        assert config.venvdir == str(venvdir)

        # test via env
        monkeypatch.setenv("WORKON_HOME", venvdir.dirpath())
        hub = Hub()
        venvpath = hub.path_venvbase.join(venvdir.basename)
        assert venvpath == venvdir

