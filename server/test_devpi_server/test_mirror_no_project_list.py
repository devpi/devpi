from bs4 import BeautifulSoup
from devpi_common.metadata import splitbasename
from devpi_server.model import Unknown
import pytest


def getlinks(text):
    return BeautifulSoup(text, "html.parser").find_all("a")


def register_and_store(stage, basename, content=b"123", name=None):
    assert isinstance(content, bytes), content
    n, version = splitbasename(basename)[:2]
    if name is None:
        name = n
    stage.set_versiondata(dict(name=name, version=version))
    res = stage.store_releasefile(name, version, basename, content)
    return res


@pytest.fixture
def mirrorapi(mapp, simpypi):
    mapp.login("root")
    mapp.modify_index(
        "root/pypi", indexconfig=dict(
            type="mirror",
            mirror_cache_expiry=0,
            mirror_no_project_list=True,
            mirror_url=simpypi.simpleurl))
    return mapp.use("root/pypi")


@pytest.fixture
def mirrorstage(model, simpypi):
    stage = model.getstage("root", "pypi")
    stage.ixconfig["mirror_no_project_list"] = True
    stage.ixconfig["mirror_url"] = simpypi.simpleurl
    return stage


@pytest.fixture
def stage(mirrorstage, user):
    config = dict(
        index="world",
        bases=(mirrorstage.name,),
        type="stage",
        volatile=True)
    return user.create_stage(**config)


@pytest.fixture
def user(model):
    return model.create_user("hello", password="123")


def test_unknown():
    assert bool(Unknown) is False
    assert (not Unknown) is True
    assert repr(Unknown) == "<Unknown>"


@pytest.mark.nomocking
@pytest.mark.notransaction
def test_listing_projects(mapp, mirrorapi, simpypi, testapp):
    data = mapp.getjson(f"/{mirrorapi.stagename}")
    assert data["result"]["projects"] == []
    r = testapp.get(mirrorapi.simpleindex)
    assert "root/pypi: simple list" in r.text
    assert "<a" not in r.text
    assert simpypi.log == []
    assert simpypi.requests == []
    simpypi.add_release("pkg", pkgver="pkg-1.0.zip")
    # after the package is added, there is still no project list
    data = mapp.getjson(f"/{mirrorapi.stagename}")
    assert data["result"]["projects"] == []
    r = testapp.get(mirrorapi.simpleindex)
    assert "root/pypi: simple list" in r.text
    assert "<a" not in r.text
    assert simpypi.log == []
    assert simpypi.requests == []
    # fetch releases directly
    (link,) = mapp.getreleaseslist("pkg")
    assert link.endswith("pkg-1.0.zip")
    # this fetches from upstream
    assert simpypi.log
    assert set(x[0] for x in simpypi.requests) == {"/simple/pkg/"}
    # now we see the project listed, but no fetch from upstream when listing
    simpypi.clear()
    data = mapp.getjson(f"/{mirrorapi.stagename}")
    assert data["result"]["projects"] == ["pkg"]
    r = testapp.get(mirrorapi.simpleindex)
    assert "root/pypi: simple list" in r.text
    (link,) = getlinks(r.text)
    assert link.text == "pkg"
    assert "pkg" in link.attrs["href"]
    assert simpypi.log == []
    assert simpypi.requests == []


@pytest.mark.nomocking
def test_has_project_perstage(mirrorstage, simpypi):
    assert mirrorstage.has_project_perstage("pkg") is Unknown
    assert simpypi.log == []
    assert simpypi.requests == []
    simpypi.add_release("pkg", pkgver="pkg-1.0.zip")
    assert mirrorstage.has_project_perstage("pkg") is Unknown
    assert simpypi.log == []
    assert simpypi.requests == []
    (link,) = mirrorstage.get_releaselinks_perstage("pkg")
    assert link.basename == "pkg-1.0.zip"
    assert simpypi.log
    assert set(x[0] for x in simpypi.requests) == {"/simple/pkg/"}
    simpypi.clear()
    assert mirrorstage.has_project_perstage("pkg") is True
    assert simpypi.log == []
    assert simpypi.requests == []


@pytest.mark.nomocking
@pytest.mark.writetransaction
def test_get_releaselinks_with_upstream(mirrorstage, simpypi, stage):
    simpypi.add_release("pkg", pkgver="pkg-1.0.zip")
    assert stage.has_project("pkg") is Unknown
    (link,) = stage.get_releaselinks("pkg")
    assert link.basename == "pkg-1.0.zip"
    assert simpypi.log
    assert set(x[0] for x in simpypi.requests) == {"/simple/pkg/"}


@pytest.mark.nomocking
@pytest.mark.writetransaction
def test_get_mirror_whitelist_info_without_upstream(mirrorstage, simpypi, stage):
    assert stage.has_project("pkg") is Unknown
    info = stage.get_mirror_whitelist_info("pkg")
    assert info["has_mirror_base"] is Unknown
    assert info["blocked_by_mirror_whitelist"] is None
    assert simpypi.log == []
    assert simpypi.requests == []
    register_and_store(stage, "pkg-1.0.zip")
    assert stage.has_project("pkg") is True
    info = stage.get_mirror_whitelist_info("pkg")
    assert info["has_mirror_base"] is Unknown
    assert info["blocked_by_mirror_whitelist"] == "root/pypi"
    (link,) = stage.get_releaselinks("pkg")
    assert link.basename == "pkg-1.0.zip"
    assert simpypi.log == []
    assert simpypi.requests == []


@pytest.mark.nomocking
@pytest.mark.writetransaction
def test_get_mirror_whitelist_info_with_unfetched_upstream(mirrorstage, simpypi, stage):
    simpypi.add_release("pkg", pkgver="pkg-1.0.zip")
    assert stage.has_project("pkg") is Unknown
    info = stage.get_mirror_whitelist_info("pkg")
    assert info["has_mirror_base"] is Unknown
    assert info["blocked_by_mirror_whitelist"] is None
    assert simpypi.log == []
    assert simpypi.requests == []
    register_and_store(stage, "pkg-1.0.zip")
    assert stage.has_project("pkg") is True
    info = stage.get_mirror_whitelist_info("pkg")
    assert info["has_mirror_base"] is Unknown
    assert info["blocked_by_mirror_whitelist"] == "root/pypi"
    (link,) = stage.get_releaselinks("pkg")
    assert link.basename == "pkg-1.0.zip"
    assert simpypi.log == []
    assert simpypi.requests == []


@pytest.mark.nomocking
@pytest.mark.writetransaction
def test_get_mirror_whitelist_info_with_fetched_upstream(mirrorstage, simpypi, stage):
    simpypi.add_release("pkg", pkgver="pkg-1.0.zip")
    (link,) = mirrorstage.get_releaselinks_perstage("pkg")
    assert link.basename == "pkg-1.0.zip"
    assert stage.has_project("pkg") is True
    assert simpypi.log
    assert set(x[0] for x in simpypi.requests) == {"/simple/pkg/"}
    simpypi.clear()
    info = stage.get_mirror_whitelist_info("pkg")
    assert info["has_mirror_base"] is True
    assert info["blocked_by_mirror_whitelist"] is None
    assert simpypi.log == []
    assert simpypi.requests == []
    register_and_store(stage, "pkg-1.0.zip")
    assert stage.has_project("pkg") is True
    info = stage.get_mirror_whitelist_info("pkg")
    assert info["has_mirror_base"] is Unknown
    assert info["blocked_by_mirror_whitelist"] == "root/pypi"
    (link,) = stage.get_releaselinks("pkg")
    assert link.basename == "pkg-1.0.zip"
    assert simpypi.log == []
    assert simpypi.requests == []


@pytest.mark.nomocking
@pytest.mark.writetransaction
def test_whitelisted_with_unfetched_upstream(mirrorstage, simpypi, stage):
    stage.ixconfig["mirror_whitelist"] = ["pkg"]
    simpypi.add_release("pkg", pkgver="pkg-1.0.zip")
    assert stage.has_project("pkg") is Unknown
    info = stage.get_mirror_whitelist_info("pkg")
    assert info["has_mirror_base"] is Unknown
    assert info["blocked_by_mirror_whitelist"] is None
    assert simpypi.log == []
    assert simpypi.requests == []
    register_and_store(stage, "pkg-1.0.zip")
    assert stage.has_project("pkg") is True
    info = stage.get_mirror_whitelist_info("pkg")
    assert info["has_mirror_base"] is Unknown
    assert info["blocked_by_mirror_whitelist"] is None
    assert simpypi.log == []
    assert simpypi.requests == []
    (link,) = stage.get_releaselinks("pkg")
    assert link.basename == "pkg-1.0.zip"
    assert simpypi.log
    assert set(x[0] for x in simpypi.requests) == {"/simple/pkg/"}


@pytest.mark.nomocking
@pytest.mark.writetransaction
def test_whitelisted_with_fetched_upstream(mirrorstage, simpypi, stage):
    stage.ixconfig["mirror_whitelist"] = ["pkg"]
    simpypi.add_release("pkg", pkgver="pkg-1.0.zip")
    (link,) = mirrorstage.get_releaselinks_perstage("pkg")
    assert link.basename == "pkg-1.0.zip"
    assert stage.has_project("pkg") is True
    assert simpypi.log
    assert set(x[0] for x in simpypi.requests) == {"/simple/pkg/"}
    simpypi.clear()
    info = stage.get_mirror_whitelist_info("pkg")
    assert info["has_mirror_base"] is True
    assert info["blocked_by_mirror_whitelist"] is None
    assert simpypi.log == []
    assert simpypi.requests == []
    register_and_store(stage, "pkg-1.0.zip")
    assert stage.has_project("pkg") is True
    info = stage.get_mirror_whitelist_info("pkg")
    assert info["has_mirror_base"] is True
    assert info["blocked_by_mirror_whitelist"] is None
    assert simpypi.log == []
    assert simpypi.requests == []
    (link,) = stage.get_releaselinks("pkg")
    assert link.basename == "pkg-1.0.zip"
    assert simpypi.log
    assert set(x[0] for x in simpypi.requests) == {"/simple/pkg/"}
