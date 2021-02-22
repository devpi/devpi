from __future__ import unicode_literals
import getpass
import inspect
import itertools
import py
import pytest
import json

from devpi_common.metadata import splitbasename
from devpi_common.archive import Archive, zip_dict
from devpi_server.config import hookimpl
from devpi_server.model import InvalidIndexconfig
from devpi_server.model import PrivateStage
from devpi_server.model import ensure_boolean
from devpi_server.model import ensure_acl_list
from devpi_server.model import ensure_list
from devpi_server.model import run_passwd
from devpi_server.model import StageCustomizer
from py.io import BytesIO

pytestmark = [pytest.mark.writetransaction]


def udict(**kw):
    """ return a dict where the keys are normalized to unicode. """
    d = {}
    for name, val in kw.items():
        d[py.builtin._totext(name)] = val
    return d


@pytest.fixture(params=[(), ("root/pypi",)])
def bases(request):
    return request.param


def get_release_basenames(stage, project):
    return sorted(
        x.basename
        for x in stage.get_releaselinks(project))


def register_and_store(stage, basename, content=b"123", name=None):
    assert py.builtin._isbytes(content), content
    n, version = splitbasename(basename)[:2]
    if name is None:
        name = n
    stage.set_versiondata(udict(name=name, version=version))
    res = stage.store_releasefile(name, version, basename, content)
    return res


@pytest.fixture
def stage(request, user):
    config = udict(index="world", bases=(), type="stage", volatile=True)
    if "bases" in request.fixturenames:
        config["bases"] = request.getfixturevalue("bases")
    return user.create_stage(**config)


@pytest.fixture
def user(model):
    return model.create_user("hello", password="123")


def test_has_mirror_base(model, pypistage):
    pypistage.mock_simple("pytest", "<a href='pytest-1.0.zip' /a>")
    assert pypistage.has_mirror_base("pytest")
    assert pypistage.has_project_perstage("pytest")
    user = model.create_user("user1", "pass")
    stage1 = user.create_stage("stage1", bases=())
    assert not stage1.has_mirror_base("pytest")

    stage2 = user.create_stage("stage2", bases=("root/pypi",))
    assert stage2.has_mirror_base("pytest")
    register_and_store(stage2, "pytest-1.1.tar.gz")
    assert not stage2.has_mirror_base("pytest")
    ixconfig = stage2.ixconfig.copy()
    ixconfig["mirror_whitelist"] = ["pytest"]
    stage2.modify(**ixconfig)
    assert stage2.has_mirror_base("pytest")


def test_get_mirror_whitelist_info(model, pypistage):
    pypistage.mock_simple("pytest", "<a href='pytest-1.0.zip' /a>")
    assert pypistage.get_mirror_whitelist_info("pytest") == dict(
        has_mirror_base=True,
        blocked_by_mirror_whitelist=None)
    user = model.create_user("user1", "pass")
    stage1 = user.create_stage("stage1", bases=())
    assert stage1.get_mirror_whitelist_info("pytest") == dict(
        has_mirror_base=False,
        blocked_by_mirror_whitelist=None)
    register_and_store(stage1, "pytest-1.1.tar.gz")
    assert stage1.get_mirror_whitelist_info("pytest") == dict(
        has_mirror_base=False,
        blocked_by_mirror_whitelist=None)
    stage2 = user.create_stage("stage2", bases=("root/pypi",))
    assert stage2.get_mirror_whitelist_info("pytest") == dict(
        has_mirror_base=True,
        blocked_by_mirror_whitelist=None)
    register_and_store(stage2, "pytest-1.1.tar.gz")
    assert stage2.get_mirror_whitelist_info("pytest") == dict(
        has_mirror_base=False,
        blocked_by_mirror_whitelist='root/pypi')
    # now add to whitelist
    ixconfig = stage2.ixconfig.copy()
    ixconfig["mirror_whitelist"] = ["pytest"]
    stage2.modify(**ixconfig)
    assert stage2.get_mirror_whitelist_info("pytest") == dict(
        has_mirror_base=True,
        blocked_by_mirror_whitelist=None)
    # now remove from whitelist
    ixconfig = stage2.ixconfig.copy()
    ixconfig["mirror_whitelist"] = []
    stage2.modify(**ixconfig)
    assert stage2.get_mirror_whitelist_info("pytest") == dict(
        has_mirror_base=False,
        blocked_by_mirror_whitelist='root/pypi')
    # and try "*"
    ixconfig = stage2.ixconfig.copy()
    ixconfig["mirror_whitelist"] = ["*"]
    stage2.modify(**ixconfig)
    assert stage2.get_mirror_whitelist_info("pytest") == dict(
        has_mirror_base=True,
        blocked_by_mirror_whitelist=None)


@pytest.mark.notransaction
def test_get_mirror_whitelist_info_private_package(mapp, monkeypatch, testapp):
    api = mapp.create_and_use(indexconfig=dict(bases=["root/pypi"]))
    mapp.set_versiondata(
        {"name": "pkg1", "version": "2.6", "description": "foo"},
        set_whitelist=False)
    # test that getting the whitelist info doesn't reveal package name, see #451
    with mapp.xom.model.keyfs.transaction(write=False):
        with monkeypatch.context() as m:
            # make sure we get an error if data is fetched
            m.setattr(mapp.xom, 'httpget', None)
            stage = mapp.xom.model.getstage(api.stagename)
            info = stage.get_mirror_whitelist_info("pkg1")
            assert info['has_mirror_base'] is False
            assert info['blocked_by_mirror_whitelist'] == "root/pypi"
    mapp.use("root/pypi")
    mapp.xom.httpget.mock_simple("pkg1", text="")
    mapp.get_simple("pkg1")
    with mapp.xom.model.keyfs.transaction(write=False):
        with monkeypatch.context() as m:
            # make sure we get an error if data is fetched
            m.setattr(mapp.xom, 'httpget', None)
            pypistage = mapp.xom.model.getstage("root/pypi")
            # expire the project data, otherwise we wouldn't fetch data
            # by accident
            pypistage.cache_retrieve_times.expire("pkg1")
            # now we check that we get correct info without fetching data
            stage = mapp.xom.model.getstage(api.stagename)
            info = stage.get_mirror_whitelist_info("pkg1")
            assert info['has_mirror_base'] is False
            assert info['blocked_by_mirror_whitelist'] == "root/pypi"
    # now we whitelist the package
    testapp.patch_json("/" + api.stagename, ["mirror_whitelist+=pkg1"])
    with mapp.xom.model.keyfs.transaction(write=False):
        stage = mapp.xom.model.getstage(api.stagename)
        info = stage.get_mirror_whitelist_info("pkg1")
        assert info['has_mirror_base'] is True
        assert info['blocked_by_mirror_whitelist'] is None


@pytest.fixture
def queue(TimeoutQueue):
    return TimeoutQueue()


class TestStage:
    def test_create_and_delete(self, model):
        user = model.create_user("hello", password="123")
        user.create_stage("world", bases=(), type="stage", volatile=False)
        user.create_stage("world2", bases=(), type="stage", volatile=False)
        stage = model.getstage("hello", "world2")
        stage.delete()
        assert model.getstage("hello", "world2") is None
        assert model.getstage("hello", "world") is not None

    def test_store_and_retrieve_simple(self, stage):
        register_and_store(stage, "someproject-1.1.tar.gz")
        assert len(stage.get_simplelinks_perstage("someproject")) == 1
        assert len(stage.get_releaselinks_perstage("someproject")) == 1

    @pytest.mark.with_notifier
    def test_delete_user_hooks_issue228(self, model, caplog):
        keyfs = model.xom.keyfs
        keyfs.commit_transaction_in_thread()
        with keyfs.transaction(write=True):
            user = model.create_user("hello", password="123")
            user.create_stage("world", bases=(), type="stage", volatile=False)
            stage = model.getstage("hello", "world")
            register_and_store(stage, "someproject-1.0.zip", b"123")
        with keyfs.transaction(write=True):
            user.delete()
        serial = keyfs.get_current_serial()
        keyfs.notifier.wait_event_serial(serial)
        assert not caplog.getrecords(minlevel="ERROR")

    def test_getstage_normalized(self, model):
        assert model.getstage("/root/pypi/").name == "root/pypi"

    def test_not_configured_index(self, model):
        stagename = "hello/world"
        assert model.getstage(stagename) is None

    def test_indexconfig_set_throws_on_unknown_base_index(self, stage, user):
        with pytest.raises(InvalidIndexconfig) as excinfo:
            user.create_stage(index="something",
                              bases=("root/notexists", "root/notexists2"),)
        messages = excinfo.value.messages
        assert len(messages) == 2
        assert "root/notexists" in messages[0]
        assert "root/notexists2" in messages[1]

    def test_indexconfig_set_throws_on_invalid_base_index(self, stage, user):
        with pytest.raises(InvalidIndexconfig) as excinfo:
            user.create_stage(index="world3", bases=("root/dev/123",),)
        messages = excinfo.value.messages
        assert len(messages) == 1
        assert "root/dev/123" in messages[0]

    def test_indexconfig_set_normalizes_bases(self, user):
        stage = user.create_stage(index="world", bases=("/root/pypi/",))
        assert stage.ixconfig["bases"] == ("root/pypi",)

    def test_empty(self, stage, bases):
        assert not stage.has_project("someproject")
        assert not stage.list_projects_perstage()

    def test_inheritance_simple(self, pypistage, stage):
        stage.modify(bases=("root/pypi",), mirror_whitelist=['someproject'])
        pypistage.mock_simple("someproject", "<a href='someproject-1.0.zip' /a>")
        assert stage.list_projects_perstage() == set()
        links = stage.get_releaselinks("someproject")
        assert len(links) == 1
        stage.set_versiondata(udict(name="someproject", version="1.1"))
        assert stage.list_projects_perstage() == set(["someproject"])

    def test_inheritance_twice(self, pypistage, stage, user):
        user.create_stage(index="dev2", bases=("root/pypi",))
        stage_dev2 = user.getstage("dev2")
        stage.modify(bases=(stage_dev2.name,), mirror_whitelist=['someproject'])
        pypistage.mock_simple("someproject",
                              "<a href='someproject-1.0.zip' /a>")
        register_and_store(stage_dev2, "someproject-1.1.tar.gz")
        register_and_store(stage_dev2, "someproject-1.2.tar.gz")
        assert len(stage.get_simplelinks("someproject")) == 3
        links = stage.get_releaselinks("someproject")
        assert len(links) == 3
        assert links[0].basename == "someproject-1.2.tar.gz"
        assert links[1].basename == "someproject-1.1.tar.gz"
        assert links[2].basename == "someproject-1.0.zip"
        assert stage.list_projects_perstage() == set()
        assert stage_dev2.list_projects_perstage() == set(["someproject"])

    def test_inheritance_complex_issue_214(self, model):
        prov_user = model.create_user('provider', password="123")
        prov_a = prov_user.create_stage(index='A', bases=[])
        prov_b = prov_user.create_stage(index='B', bases=['provider/A'])
        aggr_user = model.create_user('aggregator', password="123")
        aggr_index = aggr_user.create_stage(index='index', bases=['provider/B'])
        cons_user = model.create_user('consumer', password="123")
        cons_index = cons_user.create_stage(index='index', bases=['aggregator/index'])
        extagg_user = model.create_user('extagg', password="123")
        extagg_index1 = extagg_user.create_stage(index='index1', bases=['root/pypi'])
        extagg_index2 = extagg_user.create_stage(index='index2', bases=['aggregator/index', 'extagg/index1'])
        content = b"123"
        register_and_store(prov_a, "pkg-1.0.zip", content)
        register_and_store(prov_a, "pkg-2.0.zip", content)
        register_and_store(prov_a, "pkg-3.0.zip", content)
        register_and_store(prov_b, "pkg-1.0.zip", content)
        register_and_store(prov_b, "pkg-2.0.zip", content)
        assert prov_a.list_versions_perstage('pkg') == set(['1.0', '2.0', '3.0'])
        assert prov_b.list_versions_perstage('pkg') == set(['1.0', '2.0'])
        assert prov_a.list_versions('pkg') == set(['1.0', '2.0', '3.0'])
        assert prov_b.list_versions('pkg') == set(['1.0', '2.0', '3.0'])
        assert aggr_index.list_versions('pkg') == set(['1.0', '2.0', '3.0'])
        assert cons_index.list_versions('pkg') == set(['1.0', '2.0', '3.0'])
        assert extagg_index1.list_versions('pkg') == set([])
        assert extagg_index2.list_versions('pkg') == set(['1.0', '2.0', '3.0'])

    def test_inheritance_complex_issue_214_pypi(self, pypistage, model):
        pypi = model.getstage('root/pypi')
        pypistage.mock_simple("pkg", """
            <a href='pkg-2.0.zip' /a>
            <a href='pkg-2.0.tar.gz' /a>
        """)
        prov_user = model.create_user('provider', password="123")
        prov_a = prov_user.create_stage(index='A', bases=[])
        prov_b = prov_user.create_stage(index='B', bases=['provider/A'])
        aggr_user = model.create_user('aggregator', password="123")
        aggr_index = aggr_user.create_stage(index='index', bases=['provider/B'])
        cons_user = model.create_user('consumer', password="123")
        cons_index = cons_user.create_stage(index='index', bases=['aggregator/index'])
        extagg_user = model.create_user('extagg', password="123")
        extagg_index1 = extagg_user.create_stage(index='index1', bases=['root/pypi'])
        extagg_index2 = extagg_user.create_stage(index='index2', bases=['aggregator/index', 'extagg/index1'])
        content = b"123"
        register_and_store(prov_a, "pkg-1.0.zip", content)
        assert pypi.list_versions_perstage('pkg') == set(['2.0'])
        assert prov_a.list_versions_perstage('pkg') == set(['1.0'])
        assert prov_b.list_versions_perstage('pkg') == set([])
        assert aggr_index.list_versions_perstage('pkg') == set([])
        assert cons_index.list_versions_perstage('pkg') == set([])
        assert extagg_index1.list_versions_perstage('pkg') == set([])
        assert extagg_index2.list_versions_perstage('pkg') == set([])
        assert pypi.list_versions('pkg') == set(['2.0'])
        assert prov_a.list_versions('pkg') == set(['1.0'])
        assert prov_b.list_versions('pkg') == set(['1.0'])
        assert aggr_index.list_versions('pkg') == set(['1.0'])
        assert cons_index.list_versions('pkg') == set(['1.0'])
        assert extagg_index1.list_versions('pkg') == set(['2.0'])
        assert extagg_index2.list_versions('pkg') == set(['1.0'])

    def test_inheritance_normalize_multipackage(self, pypistage, stage):
        stage.modify(bases=("root/pypi",), mirror_whitelist=['some-project'])
        pypistage.mock_simple("some-project", """
            <a href='some_project-1.0.zip' /a>
            <a href='some_project-1.0.tar.gz' /a>
        """)
        register_and_store(stage, "some_project-1.2.tar.gz",
                           name="some-project")
        register_and_store(stage, "some_project-1.2.tar.gz",
                           name="some-project")
        links = stage.get_releaselinks("some-project")
        assert len(links) == 3
        assert links[0].basename == "some_project-1.2.tar.gz"
        assert links[1].basename == "some_project-1.0.zip"
        assert links[2].basename == "some_project-1.0.tar.gz"
        assert stage.list_projects_perstage() == set(["some-project"])

    def test_inheritance_tolerance_on_different_names(self, stage, user):
        register_and_store(stage, "some_project-1.2.tar.gz",
                           name="some-project")
        stage2 = user.create_stage(index="dev2")
        register_and_store(stage2, "some_project-1.3.tar.gz",
                           name="Some_Project")
        stage.modify(bases=(stage2.name,))
        links = stage.get_releaselinks("some-project")
        assert len(links) == 2
        links = stage.get_releaselinks("Some_Project")
        assert len(links) == 2
        links = stage2.get_releaselinks("some_project")
        assert len(links) == 1

    def test_get_releaselinks_inheritance_shadow(self, pypistage, stage):
        stage.modify(bases=("root/pypi",), mirror_whitelist=['someproject'])
        pypistage.mock_simple("someproject",
            "<a href='someproject-1.0.zip' /a>")
        register_and_store(stage, "someproject-1.0.zip", b"123")
        stage.store_releasefile("someproject", "1.0",
                                "someproject-1.0.zip", b"123")
        links = stage.get_releaselinks("someproject")
        assert len(links) == 1
        assert links[0].entrypath.endswith("someproject-1.0.zip")

    def test_inheritance_error_are_nop(self, pypistage, stage):
        stage.modify(bases=("root/pypi",), mirror_whitelist=['someproject'])
        pypistage.mock_simple("someproject", status_code = -1)
        assert stage.get_releaselinks("someproject") == []
        assert stage.list_versions("someproject") == set([])

    def test_get_versiondata_inherited(self, pypistage, stage):
        stage.modify(bases=("root/pypi",), mirror_whitelist=['someproject'])
        pypistage.mock_simple("someproject",
            "<a href='someproject-1.0.zip' /a>")
        verdata = stage.get_versiondata("someproject", "1.0")
        assert verdata["+elinks"], verdata
        assert "someproject-1.0.zip" in str(verdata)

    def test_get_versiondata_inherit_not_exist_version(self, pypistage, stage):
        stage.modify(bases=("root/pypi",), mirror_whitelist=['someproject'])
        pypistage.mock_simple("someproject",
            "<a href='someproject-1.0.zip' /a>")
        assert not stage.get_versiondata("someproject", "2.0")

    def test_store_and_get_releasefile(self, stage, bases):
        content = b"123"
        link = register_and_store(stage, "some-1.0.zip", content)
        entry = link.entry
        assert entry.hash_spec
        assert entry.last_modified is not None
        entries = stage.get_releaselinks("some")
        assert len(entries) == 1
        assert entries[0].hash_spec == entry.hash_spec
        assert stage.list_projects_perstage() == set(["some"])
        verdata = stage.get_versiondata("some", "1.0")
        links = verdata["+elinks"]
        assert len(links) == 1
        assert links[0]["entrypath"].endswith("some-1.0.zip")

    def test_store_releasefile_fails_if_not_registered(self, stage):
        with pytest.raises(stage.MissesRegistration):
            stage.store_releasefile("someproject", "1.0",
                                    "someproject-1.0.zip", b"123")

    @pytest.mark.xfail(reason="fix tx in-place key get semantics")
    def test_store_releasefile_and_linkstore_same_tx(self, stage):
        register_and_store(stage, "someproject-1.0.zip", b"123")
        ls = stage.get_linkstore_perstage("someproject", "1.0")
        assert len(ls.get_links()) == 1
        register_and_store(stage, "someproject-1.0.tar.gz", b"123")
        assert len(ls.get_links()) == 2

    def test_project_versiondata_shadowed(self, pypistage, stage):
        stage.modify(bases=("root/pypi",), mirror_whitelist=['someproject'])
        pypistage.mock_simple("someproject",
            "<a href='someproject-1.0.zip' /a>")
        content = b"123"
        register_and_store(stage, "someproject-1.0.zip", content)
        verdata = stage.get_versiondata("someproject", "1.0")
        linkdict, = verdata["+elinks"]
        assert linkdict["entrypath"].endswith("someproject-1.0.zip")
        assert verdata["+shadowing"]

    def test_project_whitelist(self, pypistage, stage):
        stage.modify(bases=("root/pypi",))
        pypistage.mock_simple("someproject",
            "<a href='someproject-1.1.zip' /a>")
        register_and_store(stage, "someproject-1.0.zip", b"123")
        stage.store_releasefile("someproject", "1.0",
                                "someproject-1.0.zip", b"123")
        links = stage.get_releaselinks("someproject")
        # because the whitelist doesn't include "someproject" we only get
        # our upload
        assert len(links) == 1
        assert links[0].entrypath.endswith("someproject-1.0.zip")
        # if we add the project to the whitelist, we also get the release
        # from pypi
        stage.modify(mirror_whitelist=['someproject'])
        links = stage.get_releaselinks("someproject")
        assert len(links) == 2
        assert links[0].entrypath.endswith("someproject-1.1.zip")
        assert links[1].entrypath.endswith("someproject-1.0.zip")

    def test_project_whitelist_empty_project(self, pypistage, stage):
        stage.modify(bases=("root/pypi",))
        pypistage.mock_simple("someproject",
            "<a href='someproject-1.1.zip' /a>")
        stage.set_versiondata(udict(name="someproject", version="1.0"))
        links = stage.get_releaselinks("someproject")
        # because the whitelist doesn't include "someproject" we get
        # no releases, because we only registered, but didn't upload
        assert len(links) == 0

    def test_project_whitelist_nothing_in_stage(self, pypistage, stage):
        stage.modify(bases=("root/pypi",))
        pypistage.mock_simple("someproject",
            "<a href='someproject-1.1.zip' /a>")
        links = stage.get_releaselinks("someproject")
        # because the whitelist doesn't include "someproject" we get
        # no releases, because we only registered, but didn't upload
        assert len(links) == 1
        assert links[0].entrypath.endswith("someproject-1.1.zip")

    def test_project_whitelist_inheritance(self, pypistage, stage, user):
        user.create_stage(index="dev2", bases=("root/pypi",))
        stage_dev2 = user.getstage("dev2")
        stage.modify(
            mirror_whitelist_inheritance="union",
            bases=(stage_dev2.name,))
        pypistage.mock_simple("someproject",
            "<a href='someproject-1.1.zip' /a>")
        register_and_store(stage, "someproject-1.0.zip", b"123")
        stage.store_releasefile("someproject", "1.0",
                                "someproject-1.0.zip", b"123")
        links = stage.get_releaselinks("someproject")
        # because the whitelist doesn't include "someproject" we only get
        # our upload
        assert len(links) == 1
        assert links[0].entrypath.endswith("someproject-1.0.zip")
        # if we add the project to the whitelist of the inherited index, we
        # also get the release from pypi
        stage_dev2.modify(mirror_whitelist=['someproject'])
        links = stage.get_releaselinks("someproject")
        assert len(links) == 2
        assert links[0].entrypath.endswith("someproject-1.1.zip")
        assert links[1].entrypath.endswith("someproject-1.0.zip")

    def test_project_whitelist_all(self, pypistage, stage):
        stage.modify(bases=("root/pypi",))
        pypistage.mock_simple("someproject",
            "<a href='someproject-1.1.zip' /a>")
        register_and_store(stage, "someproject-1.0.zip", b"123")
        stage.store_releasefile("someproject", "1.0",
                                "someproject-1.0.zip", b"123")
        links = stage.get_releaselinks("someproject")
        # because the whitelist doesn't include "someproject" we only get
        # our upload
        assert len(links) == 1
        assert links[0].entrypath.endswith("someproject-1.0.zip")
        # if we allow all projects in the whitelist, we also get the release
        # from pypi
        stage.modify(mirror_whitelist=['*'])
        links = stage.get_releaselinks("someproject")
        assert len(links) == 2
        assert links[0].entrypath.endswith("someproject-1.1.zip")
        assert links[1].entrypath.endswith("someproject-1.0.zip")

    def test_project_whitelist_all_inheritance(self, pypistage, stage, user):
        user.create_stage(index="dev2", bases=("root/pypi",))
        stage_dev2 = user.getstage("dev2")
        stage.modify(
            mirror_whitelist_inheritance="union",
            bases=(stage_dev2.name,))
        pypistage.mock_simple("someproject",
            "<a href='someproject-1.1.zip' /a>")
        register_and_store(stage, "someproject-1.0.zip", b"123")
        stage.store_releasefile("someproject", "1.0",
                                "someproject-1.0.zip", b"123")
        links = stage.get_releaselinks("someproject")
        # because the whitelist doesn't include "someproject" we only get
        # our upload
        assert len(links) == 1
        assert links[0].entrypath.endswith("someproject-1.0.zip")
        # if we add all projects to the whitelist of the inherited index, we
        # also get the release from pypi
        stage_dev2.modify(mirror_whitelist=['*'])
        links = stage.get_releaselinks("someproject")
        assert len(links) == 2
        assert links[0].entrypath.endswith("someproject-1.1.zip")
        assert links[1].entrypath.endswith("someproject-1.0.zip")

    def test_project_whitelist_inheritance_all(self, pypistage, stage, user):
        user.create_stage(index="dev2", bases=("root/pypi",))
        stage_dev2 = user.getstage("dev2")
        stage.modify(bases=(stage_dev2.name,))
        pypistage.mock_simple("someproject",
            "<a href='someproject-1.1.zip' /a>")
        register_and_store(stage, "someproject-1.0.zip", b"123")
        stage.store_releasefile("someproject", "1.0",
                                "someproject-1.0.zip", b"123")
        links = stage.get_releaselinks("someproject")
        # because the whitelist doesn't include "someproject" we only get
        # our upload
        assert len(links) == 1
        assert links[0].entrypath.endswith("someproject-1.0.zip")
        # if we add all projects to the whitelist of the inheriting index, we
        # also get the release from pypi
        stage.modify(mirror_whitelist=['*'])
        links = stage.get_releaselinks("someproject")
        assert len(links) == 2
        assert links[0].entrypath.endswith("someproject-1.1.zip")
        assert links[1].entrypath.endswith("someproject-1.0.zip")

    @pytest.mark.parametrize("setting, expected", [
        ('someproject', ['someproject']),
        ('he_llo', ['he-llo']),
        ('he_llo,Django', ['he-llo', 'django']),
        ('foo,bar', ['foo', 'bar']),
        ('*', ['*'])])
    def test_whitelist_setting(self, pypistage, stage, setting, expected):
        stage.modify(mirror_whitelist=setting)
        ixconfig = stage.get()
        # BBB old devpi versions had pypi_whitelist, here we check that it's gone
        assert 'pypi_whitelist' not in ixconfig
        assert ixconfig['mirror_whitelist'] == expected

    def test_legacy_pypi_whitelist(self, stage):
        assert stage.ixconfig['volatile'] is True
        # now we try to modify the index with the old pypi_whitelist setting
        # which can still exist in dbs and will be sent by devpi-client
        stage.modify(pypi_whitelist=[], volatile=False)
        # if all went well, volatile should be changed
        assert stage.ixconfig['volatile'] is False
        # and pypi_whitelist ignored
        assert 'pypi_whitelist' not in stage.ixconfig

    @pytest.mark.notransaction
    def test_legacy_pypi_whitelist_removed(self, xom):
        with xom.keyfs.transaction(write=True):
            user = xom.model.create_user("hello", password="123")
            config = udict(index="world", bases=(), type="stage", volatile=True)
            user.create_stage(**config)
            with user.key.update() as userconfig:
                # here we inject the legacy setting
                userconfig['indexes']['world']['pypi_whitelist'] = []
            del user
        with xom.keyfs.transaction(write=True):
            stage = xom.model.getstage('hello/world')
            assert stage.ixconfig['volatile'] is True
            assert 'pypi_whitelist' in stage.ixconfig
            new_config = dict(stage.ixconfig)
            new_config['volatile'] = False
            # now we try to modify the index
            stage.modify(**new_config)
            assert stage.ixconfig['volatile'] is False
            assert 'pypi_whitelist' not in stage.ixconfig

    def test_package_not_in_mirror_whitelist_all(self, monkeypatch, pypistage, stage):
        stage.modify(mirror_whitelist="*", bases=(pypistage.name,))
        register_and_store(stage, "some_xyz-1.0.zip", b"123")
        # provoke error if called
        monkeypatch.setattr(
            "devpi_server.extpypi.PyPIStage.list_versions_perstage",
            lambda self, project: 0 / 0)
        assert stage.list_versions('some_xyz') == {'1.0'}

    def test_whitelist_intersection(self, pypistage, stage, user):
        pypistage.mock_simple(
            "someproject", "<a href='someproject-1.1.zip' /a>")
        stage.modify(mirror_whitelist="*", bases=(pypistage.name,))
        stage2 = user.create_stage(index='inheriting', bases=(stage.name,))
        assert stage.ixconfig['mirror_whitelist_inheritance'] == 'intersection'
        assert stage2.ixconfig['mirror_whitelist_inheritance'] == 'intersection'
        assert stage2.ixconfig['mirror_whitelist'] == []
        assert pypistage.list_versions('someproject') == {'1.1'}
        assert get_release_basenames(pypistage, 'someproject') == [
            'someproject-1.1.zip']
        assert stage.list_versions('someproject') == {'1.1'}
        assert get_release_basenames(stage, 'someproject') == [
            'someproject-1.1.zip']
        assert stage2.list_versions('someproject') == {'1.1'}
        assert get_release_basenames(stage2, 'someproject') == [
            'someproject-1.1.zip']
        register_and_store(stage, 'someproject-1.1-py2.py3-none-any.whl')
        assert stage.list_versions('someproject') == {'1.1'}
        assert get_release_basenames(stage, 'someproject') == [
            'someproject-1.1-py2.py3-none-any.whl',
            'someproject-1.1.zip']
        assert stage2.list_versions('someproject') == {'1.1'}
        assert get_release_basenames(stage2, 'someproject') == [
            'someproject-1.1-py2.py3-none-any.whl']
        register_and_store(stage2, 'someproject-1.0.zip')
        assert stage2.list_versions('someproject') == {'1.0', '1.1'}
        assert get_release_basenames(stage2, 'someproject') == [
            'someproject-1.0.zip',
            'someproject-1.1-py2.py3-none-any.whl']

    def test_whitelist_intersection_two_mirrors(self, httpget, stage, user):
        mirror1 = user.create_stage("mirror1", **udict(
            mirror_url="http://pypi.org/simple", type="mirror"))
        mirror2 = user.create_stage("mirror2", **udict(
            mirror_url="http://example.com/simple", type="mirror"))
        httpget.mock_simple(
            "someproject", "<a href='someproject-1.1.zip' /a>",
            remoteurl=mirror1.mirror_url)
        httpget.mock_simple(
            "someproject", "<a href='someproject-1.1-py2.py3-none-any.whl' /a>",
            remoteurl=mirror2.mirror_url)
        stage.modify(
            bases=(mirror1.name, mirror2.name),
            mirror_whitelist='*')
        stage2 = user.create_stage(index='inheriting', bases=(stage.name,))
        assert stage.ixconfig['mirror_whitelist_inheritance'] == 'intersection'
        assert stage2.ixconfig['mirror_whitelist_inheritance'] == 'intersection'
        assert mirror1.list_versions('someproject') == {'1.1'}
        assert get_release_basenames(mirror1, 'someproject') == [
            'someproject-1.1.zip']
        assert mirror2.list_versions('someproject') == {'1.1'}
        assert get_release_basenames(mirror2, 'someproject') == [
            'someproject-1.1-py2.py3-none-any.whl']
        assert stage.list_versions('someproject') == {'1.1'}
        assert get_release_basenames(stage, 'someproject') == [
            'someproject-1.1-py2.py3-none-any.whl',
            'someproject-1.1.zip']
        assert stage2.list_versions('someproject') == {'1.1'}
        assert get_release_basenames(stage2, 'someproject') == [
            'someproject-1.1-py2.py3-none-any.whl',
            'someproject-1.1.zip']
        register_and_store(stage, 'someproject-1.0.zip')
        assert stage.list_versions('someproject') == {'1.0', '1.1'}
        assert get_release_basenames(stage, 'someproject') == [
            'someproject-1.0.zip',
            'someproject-1.1-py2.py3-none-any.whl',
            'someproject-1.1.zip']
        assert stage2.list_versions('someproject') == {'1.0'}
        assert get_release_basenames(stage2, 'someproject') == [
            'someproject-1.0.zip']

    def test_whitelist_union(self, pypistage, stage, user):
        pypistage.mock_simple(
            "someproject", "<a href='someproject-1.1.zip' /a>")
        stage.modify(mirror_whitelist="*", bases=(pypistage.name,))
        stage2 = user.create_stage(
            index='inheriting', bases=(stage.name,),
            mirror_whitelist_inheritance='union')
        assert stage.ixconfig['mirror_whitelist_inheritance'] == 'intersection'
        assert stage2.ixconfig['mirror_whitelist_inheritance'] == 'union'
        assert stage2.ixconfig['mirror_whitelist'] == []
        assert pypistage.list_versions('someproject') == {'1.1'}
        assert get_release_basenames(pypistage, 'someproject') == [
            'someproject-1.1.zip']
        assert stage.list_versions('someproject') == {'1.1'}
        assert get_release_basenames(stage, 'someproject') == [
            'someproject-1.1.zip']
        assert stage2.list_versions('someproject') == {'1.1'}
        assert get_release_basenames(stage2, 'someproject') == [
            'someproject-1.1.zip']
        register_and_store(stage, 'someproject-1.1-py2.py3-none-any.whl')
        assert stage.list_versions('someproject') == {'1.1'}
        assert get_release_basenames(stage, 'someproject') == [
            'someproject-1.1-py2.py3-none-any.whl',
            'someproject-1.1.zip']
        assert stage2.list_versions('someproject') == {'1.1'}
        assert get_release_basenames(stage2, 'someproject') == [
            'someproject-1.1-py2.py3-none-any.whl',
            'someproject-1.1.zip']
        register_and_store(stage2, 'someproject-1.0.zip')
        assert stage2.list_versions('someproject') == {'1.0', '1.1'}
        assert get_release_basenames(stage2, 'someproject') == [
            'someproject-1.0.zip',
            'someproject-1.1-py2.py3-none-any.whl',
            'someproject-1.1.zip']

    def test_whitelist_union_two_mirrors(self, httpget, stage, user):
        mirror1 = user.create_stage("mirror1", **udict(
            mirror_url="http://pypi.org/simple", type="mirror"))
        mirror2 = user.create_stage("mirror2", **udict(
            mirror_url="http://example.com/simple", type="mirror"))
        httpget.mock_simple(
            "someproject", "<a href='someproject-1.1.zip' /a>",
            remoteurl=mirror1.mirror_url)
        httpget.mock_simple(
            "someproject", "<a href='someproject-1.1-py2.py3-none-any.whl' /a>",
            remoteurl=mirror2.mirror_url)
        stage.modify(
            bases=(mirror1.name, mirror2.name),
            mirror_whitelist='*')
        stage2 = user.create_stage(
            index='inheriting', bases=(stage.name,),
            mirror_whitelist_inheritance='union')
        assert stage.ixconfig['mirror_whitelist_inheritance'] == 'intersection'
        assert stage2.ixconfig['mirror_whitelist_inheritance'] == 'union'
        assert mirror1.list_versions('someproject') == {'1.1'}
        assert get_release_basenames(mirror1, 'someproject') == [
            'someproject-1.1.zip']
        assert mirror2.list_versions('someproject') == {'1.1'}
        assert get_release_basenames(mirror2, 'someproject') == [
            'someproject-1.1-py2.py3-none-any.whl']
        assert stage.list_versions('someproject') == {'1.1'}
        assert get_release_basenames(stage, 'someproject') == [
            'someproject-1.1-py2.py3-none-any.whl',
            'someproject-1.1.zip']
        assert stage2.list_versions('someproject') == {'1.1'}
        assert get_release_basenames(stage2, 'someproject') == [
            'someproject-1.1-py2.py3-none-any.whl',
            'someproject-1.1.zip']
        register_and_store(stage, 'someproject-1.0.zip')
        assert stage.list_versions('someproject') == {'1.0', '1.1'}
        assert get_release_basenames(stage, 'someproject') == [
            'someproject-1.0.zip',
            'someproject-1.1-py2.py3-none-any.whl',
            'someproject-1.1.zip']
        assert stage2.list_versions('someproject') == {'1.0', '1.1'}
        assert get_release_basenames(stage2, 'someproject') == [
            'someproject-1.0.zip',
            'someproject-1.1-py2.py3-none-any.whl',
            'someproject-1.1.zip']

    @pytest.mark.notransaction
    def test_mirror_whitelist_inheritance_bbb(self, xom):
        keyfs = xom.keyfs
        model = xom.model
        with keyfs.transaction(write=True):
            user = model.create_user("hello", password="123")
            config = udict(index="world", bases=(), type="stage", volatile=True)
            stage = user.create_stage(**config)
            assert stage.ixconfig["mirror_whitelist_inheritance"] == "intersection"
            assert stage.get_whitelist_inheritance() == "intersection"
            with user.key.update() as userconfig:
                # here we remove the value to simulate an old stage
                del userconfig['indexes']['world']['mirror_whitelist_inheritance']
        with keyfs.transaction(write=False):
            stage = xom.model.getstage("hello/world")
            assert 'mirror_whitelist_inheritance' not in stage.ixconfig
            assert stage.get_whitelist_inheritance() == "union"
        with keyfs.transaction(write=True):
            stage = xom.model.getstage("hello/world")
            # now modify an unrelated setting
            stage.modify(bases=("root/pypi",))
        with keyfs.transaction(write=False):
            stage = xom.model.getstage("hello/world")
            # mirror_whitelist_inheritance should still be missing
            assert 'mirror_whitelist_inheritance' not in stage.ixconfig
            assert stage.get_whitelist_inheritance() == "union"

    def test_store_and_delete_project(self, stage):
        register_and_store(stage, "some_xyz-1.0.zip", b"123")
        assert stage.get_versiondata_perstage("Some_xyz", "1.0")
        assert stage.get_versiondata_perstage("SOME_XYZ", "1.0")
        assert stage.get_versiondata_perstage("some-xyz", "1.0")
        stage.del_project("SoMe-XYZ")
        assert not stage.list_versions_perstage("Some-xyz")
        assert not stage.list_versions_perstage("Some_xyz")

    def test_store_and_delete_release(self, stage):
        register_and_store(stage, "Some_xyz-1.0.zip")
        register_and_store(stage, "Some_xyz-1.1.zip")
        # the name in versiondata is the "display" name, the originally
        # registered name.
        assert stage.get_versiondata_perstage("SOME_xYz", "1.0")["name"] == "Some_xyz"
        assert stage.get_versiondata_perstage("some-xyz", "1.1")["name"] == "Some_xyz"
        stage.del_versiondata("SOME-XYZ", "1.0")
        assert not stage.get_versiondata_perstage("SOME_xyz", "1.0")
        assert stage.get_versiondata_perstage("SOME-xyz", "1.1") == \
               stage.get_versiondata_perstage("some-xyz", "1.1")
        stage.del_versiondata("SomE_xyz", "1.1")
        assert not stage.has_project_perstage("SOME-xyz")
        assert not stage.has_project_perstage("some-xyz")

    def test_delete_not_existing(self, stage, bases):
        with pytest.raises(stage.NotFound, match="^project.*not found"):
            stage.del_versiondata("hello", "1.0")
        register_and_store(stage, "hello-1.0.zip")
        stage.del_versiondata("hello", "1.0", cleanup=False)
        with pytest.raises(stage.NotFound, match="^version.*not found"):
            stage.del_versiondata("hello", "1.0")

    def test_releasefile_sorting(self, stage, bases):
        register_and_store(stage, "some-1.1.zip")
        register_and_store(stage, "some-1.0.zip")
        entries = stage.get_releaselinks("some")
        assert len(entries) == 2
        assert entries[0].basename == "some-1.1.zip"

    def test_set_versiondata_twice(self, stage, bases, caplog):
        stage.set_versiondata(udict(name="pkg1", version="1.0"))
        stage.xom.keyfs.commit_transaction_in_thread()
        with stage.xom.keyfs.transaction(write=True):
            stage.set_versiondata(udict(name="pkg1", version="1.0"))
        assert caplog.getrecords("nothing to commit")

    def test_getdoczip(self, stage, bases, tmpdir):
        stage.set_versiondata(udict(name="pkg1", version="1.0"))
        assert not stage.get_doczip("pkg1", "1.0")
        content = zip_dict({"index.html": "<html/>",
            "_static": {}, "_templ": {"x.css": ""}})
        stage.store_doczip("pkg1", "1.0", content)
        doczip = stage.get_doczip("pkg1", "1.0")
        assert doczip
        with Archive(BytesIO(doczip)) as archive:
            archive.extract(tmpdir)
        assert tmpdir.join("index.html").read() == "<html/>"
        assert tmpdir.join("_static").check(dir=1)
        assert tmpdir.join("_templ", "x.css").check(file=1)

    def test_multiple_store_doczip_uses_project(self, stage, bases, tmpdir):
        # check that two store_doczip calls with slightly
        # different names will not lead to two doczip entries
        stage.set_versiondata(udict(name="pkg1", version="1.0"))
        stage.store_doczip("pkg1", "1.0", zip_dict({}))
        content2 = zip_dict({"index.html": "<html/>"})
        stage.store_doczip("Pkg1", "1.0", content2)

        # check we have only have one doczip link
        linkstore = stage.get_linkstore_perstage("pkg1", "1.0")
        links = linkstore.get_links(rel="doczip")
        assert len(links) == 1

        # get doczip and check it's really the latest one
        doczip2 = stage.get_doczip("pkg1", "1.0")
        with Archive(BytesIO(doczip2)) as archive:
            archive.extract(tmpdir)
        assert tmpdir.join("index.html").read() == "<html/>"

    def test_simulate_multiple_doczip_entries(self, stage, bases, tmpdir):
        stage.set_versiondata(udict(name="pkg1", version="1.0"))
        stage.store_doczip("pkg1", "1.0", zip_dict({}))

        # simulate a second entry with a slightly different name
        # (XXX not clear if this test is really neccessary. hpk thinks for
        # exporting state from server<2.1.5 with such a double-entry one
        # needs to install 2.1.5 and export from there anyway, clearing
        # the problem. Then again server<2.3.2 allowed the store_doczip
        # method to construct doczip filenames which differ only in
        # casing)
        linkstore = stage.get_linkstore_perstage("Pkg1", "1.0", readonly=False)
        content = zip_dict({"index.html": "<html/>"})
        linkstore.create_linked_entry(
                rel="doczip",
                basename="Pkg1-1.0.doc.zip",
                file_content=content,
        )

        # check we have two doczip links
        linkstore = stage.get_linkstore_perstage("pkg1", "1.0")
        links = linkstore.get_links(rel="doczip")
        assert len(links) == 2

        # get doczip and check it's really the latest one
        doczip = stage.get_doczip("pkg1", "1.0")
        assert doczip == content

    def test_storedoczipfile(self, stage, bases):
        from devpi_common.archive import Archive
        stage.set_versiondata(udict(name="pkg1", version="1.0"))
        content = zip_dict({"index.html": "<html/>",
            "_static": {}, "_templ": {"x.css": ""}})
        stage.store_doczip("pkg1", "1.0", content)
        archive = Archive(BytesIO(stage.get_doczip("pkg1", "1.0")))
        assert 'index.html' in archive.namelist()

        content = zip_dict({"nothing": "hello"})
        stage.store_doczip("pkg1", "1.0", content)
        archive = Archive(BytesIO(stage.get_doczip("pkg1", "1.0")))
        namelist = archive.namelist()
        assert 'nothing' in namelist
        assert 'index.html' not in namelist
        assert '_static' not in namelist
        assert '_templ' not in namelist

    def test_storetoxresult(self, stage, bases):
        content = b'123'
        link = register_and_store(stage, "pkg1-1.0.tar.gz", content=content)
        entry = link.entry
        assert entry.project == "pkg1"
        assert entry.version == "1.0"
        toxresultdata = {'hello': 'world'}
        tlink = stage.store_toxresult(link, toxresultdata)
        assert tlink.entry.file_exists()
        linkstore = stage.get_linkstore_perstage("pkg1", "1.0")
        tox_links = list(linkstore.get_links(rel="toxresult"))
        assert len(tox_links) == 1
        tentry = tox_links[0].entry
        assert tentry.basename.startswith("pkg1-1.0.tar.gz.toxresult-")
        # check that tentry is in the same dir than entry
        assert tentry.relpath.startswith(entry.relpath)

        back_data = json.loads(tentry.file_get_content().decode("utf8"))
        assert back_data == toxresultdata

        assert tentry.project == entry.project
        assert tentry.version == entry.version

        results = stage.get_toxresults(link)
        assert len(results) == 1
        assert results[0] == toxresultdata

    def test_store_and_get_volatile(self, stage):
        stage.modify(volatile=False)
        content = b"123"
        content2 = b"1234"
        entry = register_and_store(stage, "some-1.0.zip", content)
        assert len(stage.get_releaselinks("some")) == 1

        # rewrite  fails because index is non-volatile
        with pytest.raises(stage.NonVolatile):
            stage.store_releasefile("some", "1.0", "some-1.0.zip", content2)

        # rewrite succeeds with volatile
        stage.modify(volatile=True)
        entry = stage.store_releasefile("some", "1.0",
                                        "some-1.0.zip", content2)
        assert not isinstance(entry, int), entry
        links = stage.get_releaselinks("some")
        assert len(links) == 1
        assert links[0].entry.file_get_content() == content2

    def test_releasedata(self, stage):
        assert stage.metadata_keys
        assert not stage.get_versiondata("hello", "1.0")
        stage.set_versiondata(udict(name="hello", version="1.0", author="xy"))
        d = stage.get_versiondata("hello", "1.0")
        assert d["author"] == "xy"
        #stage.ixconfig["volatile"] = False
        #with pytest.raises(stage.MetadataExists):
        #    stage.set_versiondata(udict(name="hello", version="1.0"))
        #

    def test_filename_version_mangling_issue68(self, stage):
        assert not stage.get_versiondata("hello", "1.0")
        metadata = udict(name="hello", version="1.0-test")
        stage.set_versiondata(metadata)
        stage.store_releasefile("hello", "1.0-test",
                            "hello-1.0_test.whl", b"")
        ver = stage.get_latest_version_perstage("hello")
        assert ver == "1.0-test"
        #stage.ixconfig["volatile"] = False
        #with pytest.raises(stage.MetadataExists):
        #    stage.set_versiondata(udict(name="hello", version="1.0"))
        #

    def test_get_versiondata_latest(self, stage):
        stage.set_versiondata(udict(name="hello", version="1.0"))
        stage.set_versiondata(udict(name="hello", version="1.1"))
        stage.set_versiondata(udict(name="hello", version="0.9"))
        assert stage.get_latest_version_perstage("hello") == "1.1"

    def test_get_versiondata_latest_inheritance(self, user, model, stage):
        stage_base_name = stage.index + "base"
        user.create_stage(index=stage_base_name, bases=(stage.name,))
        stage_sub = model.getstage(stage.username, stage_base_name)
        stage_sub.set_versiondata(udict(name="hello", version="1.0"))
        stage.set_versiondata(udict(name="hello", version="1.1"))
        assert stage_sub.get_latest_version_perstage("hello") == "1.0"
        assert stage.get_latest_version_perstage("hello") == "1.1"

    def test_releasedata_validation(self, stage):
        with pytest.raises(ValueError):
            stage.set_versiondata(udict(name="hello_", version="1.0"))

    def test_set_versiondata_take_existing_name_issue84(self, stage, caplog):
        import logging
        stage.set_versiondata(udict(name="hello-World", version="1.0"))
        for name in ("Hello-World", "hello_world"):
            caplog.handler.records = []
            caplog.set_level(logging.WARNING)
            stage.set_versiondata(udict(name=name, version="1.0"))
            rec = caplog.getrecords()
            assert not rec

    @pytest.mark.start_threads
    def test_set_versiondata_hook(self, stage, queue):
        class Plugin:
            @hookimpl
            def devpiserver_on_changed_versiondata(self,
                    stage, project, version, metadata):
                queue.put((stage, metadata))
        stage.xom.config.pluginmanager.register(Plugin())
        orig_metadata = udict(name="hello", version="1.0")
        stage.set_versiondata(orig_metadata)
        stage.xom.keyfs.commit_transaction_in_thread()
        stage2, metadata = queue.get()
        assert stage2.name == stage.name
        assert metadata == orig_metadata
        with stage.xom.keyfs.transaction(write=True):
            stage.del_versiondata("hello", "1.0")
        stage2, metadata = queue.get()
        assert stage2.name == stage.name
        assert not metadata

    @pytest.mark.start_threads
    @pytest.mark.notransaction
    def test_stage_created_hook(self, xom, queue):
        class Plugin:
            @hookimpl
            def devpiserver_stage_created(self, stage):
                queue.put(stage)
        xom.config.pluginmanager.register(Plugin())
        with xom.keyfs.transaction(write=True):
            model = xom.model
            user = model.create_user("user", "password", email="some@email.com")
            user.create_stage("hello")
        while 1:
            stage = queue.get(timeout=10)
            if stage.name != "root/pypi":
                break
        assert stage.name == "user/hello"

        with xom.keyfs.transaction(write=True):
            user.create_stage("hello2")
        assert queue.get(timeout=10).name == "user/hello2"

    @pytest.mark.start_threads
    def test_doczip_uploaded_hook(self, stage, queue):
        class Plugin:
            @hookimpl
            def devpiserver_on_upload(self, stage, project, version, link):
                queue.put((stage, project, version, link))
        stage.xom.config.pluginmanager.register(Plugin())
        stage.set_versiondata(udict(name="pkg1", version="1.0"))
        content = zip_dict({"index.html": "<html/>",
            "_static": {}, "_templ": {"x.css": ""}})
        stage.store_doczip("pkg1", "1.0", content)
        stage.xom.keyfs.commit_transaction_in_thread()
        nstage, name, version, link = queue.get()
        assert name == "pkg1"
        assert version == "1.0"
        with stage.xom.keyfs.transaction():
            assert link.entry.file_get_content() == content
        # delete, which shouldnt trigger devpiserver_on_upload
        with stage.xom.keyfs.transaction(write=True):
            linkstore = stage.get_linkstore_perstage("pkg1", "1.0", readonly=False)
            linkstore.remove_links()

        # now write again and check that we get something from the queue
        with stage.xom.keyfs.transaction(write=True):
            stage.store_doczip("pkg1", "1.0", content)
        nstage, name, version, link = queue.get()
        assert name == "pkg1" and version == "1.0"
        with stage.xom.keyfs.transaction():
            assert link.entry.file_exists()

    @pytest.mark.start_threads
    def test_doczip_remove_hook(self, stage, queue):
        class Plugin:
            @hookimpl
            def devpiserver_on_upload(self, stage, project, version, link):
                queue.put((stage, project, version, link))
        stage.xom.config.pluginmanager.register(Plugin())

        class Plugin:
            @hookimpl
            def devpiserver_on_remove_file(self, stage, relpath):
                queue.put((stage, relpath))

        stage.xom.config.pluginmanager.register(Plugin())

        # upload, should trigger devpiserver_on_upload
        stage.set_versiondata(udict(name="pkg2", version="1.0"))
        content = zip_dict({"index.html": "<html/>",
            "_static": {}, "_templ": {"x.css": ""}})
        stage.store_doczip("pkg2", "1.0", content)
        stage.xom.keyfs.commit_transaction_in_thread()
        nstage, name, version, link = queue.get()
        assert name == "pkg2"
        assert version == "1.0"
        with stage.xom.keyfs.transaction():
            assert link.entry.file_get_content() == content

        # remove, should trigger devpiserver_on_remove_file
        with stage.xom.keyfs.transaction(write=True):
            linkstore = stage.get_linkstore_perstage("pkg2", "1.0", readonly=False)
            linkstore.remove_links()
        nstage, relpath = queue.get()
        assert relpath.startswith('hello/world/+')
        assert relpath.endswith('/pkg2-1.0.doc.zip')

    def test_get_existing_project(self, stage):
        assert not stage.get_versiondata("hello", "1.0")
        assert not stage.get_versiondata("This", "1.0")
        stage.set_versiondata(udict(name="Hello", version="1.0"))
        stage.set_versiondata(udict(name="this", version="1.0"))
        assert stage.get_versiondata("hello", "1.0")
        assert stage.get_versiondata("This", "1.0")

    @pytest.mark.notransaction
    def test_get_last_change_serial_perstage(self, xom):
        current_serial = xom.keyfs.get_current_serial()
        model = xom.model
        with xom.keyfs.transaction(write=True):
            user = model.create_user("hello", password="123")
        assert current_serial == xom.keyfs.get_current_serial() - 1
        current_serial = xom.keyfs.get_current_serial()
        with xom.keyfs.transaction(write=True):
            stage = user.create_stage(**udict(
                index="world", bases=(), type="stage", volatile=True))
            with pytest.raises(KeyError, match='not commited yet'):
                stage.get_last_change_serial_perstage()
        assert current_serial == xom.keyfs.get_current_serial() - 1
        current_serial = xom.keyfs.get_current_serial()
        with xom.keyfs.transaction(write=False):
            assert stage.get_last_change_serial_perstage() == current_serial
        actions = [
            ('set_versiondata', udict(name="pkg", version="1.0")),
            ('store_releasefile', "pkg", "1.0", "pkg-1.0.zip", b""),
            ('store_doczip', "pkg", "1.0", b""),
            ('set_versiondata', udict(name="hello", version="1.0")),
            ('store_releasefile', "hello", "1.0", "hello-1.0.zip", b""),
            ('store_releasefile', "pkg", "1.0", "pkg-1.0.tar.gz", b"")]
        for action in actions:
            with xom.keyfs.transaction(write=True):
                getattr(stage, action[0])(*action[1:])
                # inside the transaction there is no change yet
                assert stage.get_last_change_serial_perstage() == current_serial
            assert current_serial == xom.keyfs.get_current_serial() - 1
            current_serial = xom.keyfs.get_current_serial()
            with xom.keyfs.transaction(write=False):
                assert stage.get_last_change_serial_perstage() == current_serial
        # create a toxresult
        with xom.keyfs.transaction(write=True):
            (link,) = stage.get_releaselinks_perstage('hello')
            stage.store_toxresult(link, {})
        assert current_serial == xom.keyfs.get_current_serial() - 1
        current_serial = xom.keyfs.get_current_serial()
        with xom.keyfs.transaction(write=False):
            assert stage.get_last_change_serial_perstage() == current_serial
        # create another stage and run the same actions
        serial_before_new_stage = xom.keyfs.get_current_serial()
        with xom.keyfs.transaction(write=True):
            stage2 = user.create_stage(**udict(
                index="world2", bases=(), type="stage", volatile=True))
        assert current_serial == xom.keyfs.get_current_serial() - 1
        current_serial = xom.keyfs.get_current_serial()
        for action in actions:
            with xom.keyfs.transaction(write=True):
                getattr(stage2, action[0])(*action[1:])
                # inside the transaction there is no change yet
                assert stage2.get_last_change_serial_perstage() == current_serial
            assert current_serial == xom.keyfs.get_current_serial() - 1
            current_serial = xom.keyfs.get_current_serial()
            with xom.keyfs.transaction(write=False):
                assert stage2.get_last_change_serial_perstage() == current_serial
        # the other stage should not have changed
        with xom.keyfs.transaction(write=False):
            assert stage.get_last_change_serial_perstage() == serial_before_new_stage
        # now we test deletions
        with xom.keyfs.transaction(write=False):
            (link,) = stage2.get_releaselinks_perstage('hello')
            entry = link.entry
        actions = [
            ('del_entry', entry, False),
            ('del_versiondata', 'hello', '1.0', False),
            ('del_project', 'hello')]
        for action in actions:
            with xom.keyfs.transaction(write=True):
                getattr(stage2, action[0])(*action[1:])
                # inside the transaction there is no change yet
                assert stage2.get_last_change_serial_perstage() == current_serial
            assert current_serial == xom.keyfs.get_current_serial() - 1
            current_serial = xom.keyfs.get_current_serial()
            with xom.keyfs.transaction(write=False):
                assert stage2.get_last_change_serial_perstage() == current_serial
        # the other stage still should not have changed
        with xom.keyfs.transaction(write=False):
            assert stage.get_last_change_serial_perstage() == serial_before_new_stage
        # modifying the stage also should not affect the other one
        with xom.keyfs.transaction(write=True):
            stage2.modify(volatile=False)
        assert current_serial == xom.keyfs.get_current_serial() - 1
        current_serial = xom.keyfs.get_current_serial()
        with xom.keyfs.transaction(write=False):
            assert stage.get_last_change_serial_perstage() == serial_before_new_stage
        # deleting the stage should not affect the other one either
        with xom.keyfs.transaction(write=True):
            stage2.delete()
            del stage2
        assert current_serial == xom.keyfs.get_current_serial() - 1
        with xom.keyfs.transaction(write=False):
            assert stage.get_last_change_serial_perstage() == serial_before_new_stage

    @pytest.mark.notransaction
    def test_get_last_project_change_serial_perstage(self, xom):
        with xom.keyfs.transaction(write=True) as tx:
            user = xom.model.create_user("hello", password="123")
            stage = user.create_stage(index="world", type="stage")
        # get_last_project_change_serial_perstage only works with
        # commited transactions
        with xom.keyfs.transaction() as tx:
            first_serial = tx.at_serial
            assert stage.list_projects_perstage() == set()
            assert stage.get_last_project_change_serial_perstage('pkg') == -1
        with xom.keyfs.transaction(write=True) as tx:
            # no change in db yet
            assert tx.at_serial == first_serial
            stage.add_project_name('pkg')
            assert stage.list_projects_perstage() == {'pkg'}
        with xom.keyfs.transaction() as tx:
            # the addition of the project name updated the db
            assert tx.at_serial == (first_serial + 1)
            assert stage.get_last_project_change_serial_perstage('pkg') == (first_serial + 1)
        with xom.keyfs.transaction(write=True) as tx:
            # no change in db yet
            assert tx.at_serial == (first_serial + 1)
            with stage.key_projects.update() as projects:
                projects.remove('pkg')
            assert stage.list_projects_perstage() == set()
        with xom.keyfs.transaction() as tx:
            # the deletion of the project name updated the db
            assert tx.at_serial == (first_serial + 2)
            # and we can't know when it happened, checking all changes in the
            # project name set would be too expensive
            assert stage.get_last_project_change_serial_perstage('pkg') == -1
        with xom.keyfs.transaction(write=True) as tx:
            # no change in db yet
            assert tx.at_serial == (first_serial + 2)
            stage.set_versiondata(udict(name='pkg', version='1.0'))
            assert stage.list_projects_perstage() == {'pkg'}
            assert stage.list_versions_perstage('pkg') == {'1.0'}
        with xom.keyfs.transaction() as tx:
            # the addition of the version updated the db
            assert tx.at_serial == (first_serial + 3)
            assert stage.get_last_project_change_serial_perstage('pkg') == (first_serial + 3)
        with xom.keyfs.transaction(write=True) as tx:
            # no change in db yet
            assert tx.at_serial == (first_serial + 3)
            stage.set_versiondata(udict(name='other', version='1.1'))
            assert stage.list_projects_perstage() == {'other', 'pkg'}
            assert stage.list_versions_perstage('other') == {'1.1'}
        with xom.keyfs.transaction() as tx:
            # the addition of the version in another project updated the db
            assert tx.at_serial == (first_serial + 4)
            # but the checked project didn't change
            assert stage.get_last_project_change_serial_perstage('pkg') == (first_serial + 3)
        with xom.keyfs.transaction(write=True) as tx:
            # no change in db yet
            assert tx.at_serial == (first_serial + 4)
            stage.set_versiondata(udict(name='pkg', version='2.0'))
            assert stage.list_projects_perstage() == {'other', 'pkg'}
            assert stage.list_versions_perstage('pkg') == {'1.0', '2.0'}
        with xom.keyfs.transaction() as tx:
            # the addition of a second version updated the db
            assert tx.at_serial == (first_serial + 5)
            assert stage.get_last_project_change_serial_perstage('pkg') == (first_serial + 5)
        with xom.keyfs.transaction(write=True) as tx:
            # no change in db yet
            assert tx.at_serial == (first_serial + 5)
            stage.del_versiondata('pkg', '2.0')
            assert stage.list_projects_perstage() == {'other', 'pkg'}
            assert stage.list_versions_perstage('pkg') == {'1.0'}
        with xom.keyfs.transaction() as tx:
            # the deletion of the version updated the db
            assert tx.at_serial == (first_serial + 6)
            assert stage.get_last_project_change_serial_perstage('pkg') == (first_serial + 6)
        with xom.keyfs.transaction(write=True) as tx:
            # no change in db yet
            assert tx.at_serial == (first_serial + 6)
            link = stage.store_releasefile('pkg', '1.0', 'pkg-1.0.zip', b'123')
        with xom.keyfs.transaction() as tx:
            # the upload of the release updated the db
            assert tx.at_serial == (first_serial + 7)
            assert stage.get_last_project_change_serial_perstage('pkg') == (first_serial + 7)
        with xom.keyfs.transaction(write=True) as tx:
            # no change in db yet
            assert tx.at_serial == (first_serial + 7)
            other_link = stage.store_releasefile('other', '1.1', 'other-1.1.zip', b'123')
        with xom.keyfs.transaction() as tx:
            # the upload of the other release updated the db
            assert tx.at_serial == (first_serial + 8)
            # but the checked project didn't change
            assert stage.get_last_project_change_serial_perstage('pkg') == (first_serial + 7)
        with xom.keyfs.transaction(write=True) as tx:
            # no change in db yet
            assert tx.at_serial == (first_serial + 8)
            # delete only the release without removing the version
            stage.del_entry(link.entry, cleanup=False)
        with xom.keyfs.transaction() as tx:
            # the deletion of the release updated the db
            assert tx.at_serial == (first_serial + 9)
            assert stage.get_last_project_change_serial_perstage('pkg') == (first_serial + 9)
        with xom.keyfs.transaction(write=True) as tx:
            # no change in db yet
            assert tx.at_serial == (first_serial + 9)
            # delete only the release without removing the version
            stage.del_entry(other_link.entry, cleanup=False)
        with xom.keyfs.transaction() as tx:
            # the deletion of the other release updated the db
            assert tx.at_serial == (first_serial + 10)
            # but the checked project didn't change
            assert stage.get_last_project_change_serial_perstage('pkg') == (first_serial + 9)
        with xom.keyfs.transaction(write=True) as tx:
            # no change in db yet
            assert tx.at_serial == (first_serial + 10)
            stage.del_project('other')
        with xom.keyfs.transaction() as tx:
            # the deletion of the other project updated the db
            assert tx.at_serial == (first_serial + 11)
            # but the checked project didn't change
            assert stage.get_last_project_change_serial_perstage('pkg') == (first_serial + 9)
        with xom.keyfs.transaction(write=True) as tx:
            # no change in db yet
            assert tx.at_serial == (first_serial + 11)
            stage.del_project('pkg')
        with xom.keyfs.transaction() as tx:
            # the deletion of the project updated the db
            assert tx.at_serial == (first_serial + 12)
            # and this time we can know when it was deleted
            assert stage.get_last_project_change_serial_perstage('pkg') == (first_serial + 12)


class TestLinkStore:
    @pytest.fixture
    def linkstore(self, stage):
        stage.set_versiondata(udict(name="proj1", version="1.0"))
        return stage.get_linkstore_perstage("proj1", "1.0", readonly=False)

    def test_store_file(self, linkstore):
        linkstore.create_linked_entry(
            rel="releasefile", basename="proj1-1.0.zip", file_content=b'123'
        )
        linkstore.create_linked_entry(
            rel="doczip", basename="proj1-1.0.doc.zip", file_content=b'123'
        )
        link, = linkstore.get_links(rel="releasefile")
        assert link.entrypath.endswith("proj1-1.0.zip")

    def test_toxresult_create_remove(self, linkstore):
        linkstore.create_linked_entry(
            rel="releasefile", basename="proj1-1.0.zip", file_content=b'123'
        )
        linkstore.create_linked_entry(
            rel="releasefile", basename="proj1-1.1.zip", file_content=b'456'
        )
        link1, link2= linkstore.get_links(rel="releasefile")
        assert link1.entrypath.endswith("proj1-1.0.zip")

        linkstore.new_reflink(rel="toxresult", file_content=b'123', for_entrypath=link1)
        linkstore.new_reflink(rel="toxresult", file_content=b'456', for_entrypath=link2)
        rlink, = linkstore.get_links(rel="toxresult", for_entrypath=link1)
        assert rlink.for_entrypath == link1.entrypath
        rlink, = linkstore.get_links(rel="toxresult", for_entrypath=link2)
        assert rlink.for_entrypath == link2.entrypath

        link1_entry = link1.entry  # queried below

        # remove one release link, which should removes its toxresults
        # and check that the other release and its toxresult is still there
        linkstore.remove_links(rel="releasefile", basename="proj1-1.0.zip")
        links = linkstore.get_links()
        assert len(links) == 2
        assert links[0].rel == "releasefile"
        assert links[1].rel == "toxresult"
        assert links[1].for_entrypath == links[0].entrypath
        assert links[0].entrypath.endswith("proj1-1.1.zip")
        assert not link1_entry.key.exists()


class TestUsers:

    def test_create_and_validate(self, model):
        user = model.get_user("user")
        assert not user
        user = model.create_user("user", "password", email="some@email.com")
        assert user
        userconfig = user.get()
        assert userconfig["email"] == "some@email.com"
        assert not set(userconfig).intersection(["pwsalt", "pwhash"])
        assert user.validate("password")
        assert not user.validate("password2")

    def test_created_and_modified(self, mock, model, monkeypatch):
        from time import strftime
        import datetime
        gmtime_mock = mock.Mock()
        monkeypatch.setattr("devpi_server.model.gmtime", gmtime_mock)
        creation_time = datetime.datetime(2021, 2, 22, 10, 51, 51).timetuple()
        gmtime_mock.return_value = creation_time
        user = model.create_user("user", "password")
        assert user
        userconfig = user.get()
        assert userconfig["created"] == strftime("%Y-%m-%dT%H:%M:%SZ", creation_time)
        assert "modified" not in userconfig
        assert "email" not in userconfig
        modification_time1 = datetime.datetime(2021, 2, 22, 10, 52, 0).timetuple()
        gmtime_mock.return_value = modification_time1
        user.modify(email="some@email.com")
        userconfig = user.get()
        assert userconfig["created"] == strftime("%Y-%m-%dT%H:%M:%SZ", creation_time)
        assert userconfig["modified"] == strftime("%Y-%m-%dT%H:%M:%SZ", modification_time1)
        assert userconfig["email"] == "some@email.com"
        # we don't change the email value, but supply created,
        # which should be ignored
        gmtime_mock.return_value = datetime.datetime(2021, 2, 22, 10, 52, 1).timetuple()
        user.modify(created=strftime("%Y-%m-%dT%H:%M:%SZ", modification_time1), email="some@email.com")
        userconfig = user.get()
        assert userconfig["created"] == strftime("%Y-%m-%dT%H:%M:%SZ", creation_time)
        assert userconfig["modified"] == strftime("%Y-%m-%dT%H:%M:%SZ", modification_time1)
        assert userconfig["email"] == "some@email.com"
        # we don't change the email value, but supply modified,
        # which should be ignored
        gmtime_mock.return_value = datetime.datetime(2021, 2, 22, 10, 52, 1).timetuple()
        user.modify(modified=strftime("%Y-%m-%dT%H:%M:%SZ", creation_time), email="some@email.com")
        userconfig = user.get()
        assert userconfig["created"] == strftime("%Y-%m-%dT%H:%M:%SZ", creation_time)
        assert userconfig["modified"] == strftime("%Y-%m-%dT%H:%M:%SZ", modification_time1)
        assert userconfig["email"] == "some@email.com"
        # we change the email value and supply created and modified
        # the email should change and modified should be set to gmtime_mock value
        modification_time2 = datetime.datetime(2021, 2, 22, 10, 52, 1).timetuple()
        gmtime_mock.return_value = modification_time2
        user.modify(
            created=strftime("%Y-%m-%dT%H:%M:%SZ", modification_time1),
            modified=strftime("%Y-%m-%dT%H:%M:%SZ", creation_time),
            email="other@email.com")
        userconfig = user.get()
        assert userconfig["created"] == strftime("%Y-%m-%dT%H:%M:%SZ", creation_time)
        assert userconfig["modified"] == strftime("%Y-%m-%dT%H:%M:%SZ", modification_time2)
        assert userconfig["email"] == "other@email.com"
        # creating a stage doesn't update modification time
        assert userconfig["indexes"] == {}
        user.create_stage("dev")
        userconfig = user.get()
        assert userconfig["created"] == strftime("%Y-%m-%dT%H:%M:%SZ", creation_time)
        assert userconfig["modified"] == strftime("%Y-%m-%dT%H:%M:%SZ", modification_time2)
        assert "dev" in userconfig["indexes"]

    def test_migrate_hash(self, caplog, model):
        from devpi_server.auth import newsalt, getpwhash
        user = model.create_user("user", "password", email="some@email.com")
        userconfig = user.get(credentials=True)
        assert 'pwsalt' not in userconfig
        assert 'pwhash' in userconfig
        salt = newsalt()
        hash = getpwhash("password", salt)
        with user.key.update() as userconfig:
            # modify directly, because the modify method doesn't allow this
            userconfig["pwsalt"] = salt
            userconfig["pwhash"] = hash
        userconfig = user.get(credentials=True)
        assert userconfig['pwsalt'] == salt
        assert userconfig['pwhash'] == hash
        # now validate and check for migration
        assert user.validate("password")
        (rec,) = caplog.getrecords(".*modified user .*")
        assert "pwsalt=None" in rec.getMessage()
        userconfig = user.get(credentials=True)
        assert 'pwsalt' not in userconfig
        assert userconfig['pwhash'].startswith("$argon2")

    def test_create_with_hash(self, model):
        user = model.get_user("user")
        assert not user
        user = model.create_user(
            "user", None,
            pwhash="$argon2i$v=19$m=102400,t=2,p=8$F2JMqVVKSSnFGEPIGQOAsA$RXW/kJM94gq00l9QWDG0OA")
        assert user
        assert user.validate("password")
        assert not user.validate("password2")

    def test_create_and_delete(self, model):
        user = model.create_user("user", password="password")
        user.delete()
        assert not user.validate("password")

    def test_create_and_list(self, model):
        baselist = model.get_usernames()
        model.create_user("user1", password="password")
        model.create_user("user2", password="password")
        model.create_user("user3", password="password")
        newusers = model.get_usernames().difference(baselist)
        assert newusers == set("user1 user2 user3".split())
        model.get_user("user3").delete()
        newusers = model.get_usernames().difference(baselist)
        assert newusers == set("user1 user2".split())

    def test_server_passwd(self, model, monkeypatch):
        monkeypatch.setattr(getpass, "getpass", lambda x: "123")
        run_passwd(model, "root")
        assert model.get_user("root").validate("123")

    def test_server_passwd_with_old_salt_hash(self, model, monkeypatch):
        from devpi_server.auth import newsalt, getpwhash
        secret = "hello"
        new_secret = "123"
        salt = newsalt()
        hash = getpwhash(secret, salt)
        user = model.get_user("root")
        with user.key.update() as userconfig:
            userconfig['pwsalt'] = salt
            userconfig['pwhash'] = hash
        userconfig = user.get(credentials=True)
        assert userconfig['pwsalt'] is not None
        assert userconfig['pwhash'] is not None
        monkeypatch.setattr(getpass, "getpass", lambda x: new_secret)
        run_passwd(model, "root")
        assert model.get_user("root").validate(new_secret)

    def test_server_email(self, model):
        email_address = "root_" + str(id) + "@mydomain"
        user = model.get_user("root")
        user.modify(email=email_address)
        assert user.get()["email"] == email_address


def test_user_set_without_indexes(model):
    user = model.create_user("user", "password", email="some@email.com")
    user.create_stage("hello")
    user._set({"password": "pass2"})
    assert model.getstage("user/hello")


@pytest.mark.notransaction
def test_setdefault_indexes(xom, model):
    from devpi_server.main import set_default_indexes
    with model.keyfs.transaction(write=True):
        set_default_indexes(xom.model)
    with model.keyfs.transaction(write=False):
        assert model.getstage("root/pypi").ixconfig["type"] == "mirror"
    with model.keyfs.transaction(write=False):
        ixconfig = model.getstage("root/pypi").ixconfig
        for key in ixconfig:
            assert py.builtin._istext(key)
        userconfig = model.get_user("root").get()
        for key in userconfig["indexes"]["pypi"]:
            assert py.builtin._istext(key)


@pytest.mark.parametrize("key", ("acl_upload", "acl_toxresult_upload", "mirror_whitelist"))
@pytest.mark.parametrize("value, result", (
    ("", []), ("x,y", ["x", "y"]), ("x,,y", ["x", "y"])))
def test_get_indexconfig_lists(xom, key, value, result):
    stage = PrivateStage(
        xom, "user", "index", {"type": "stage"}, StageCustomizer)
    kvdict = stage.get_indexconfig_from_kwargs(**{key: value})
    assert kvdict[key] == result


def test_ensure_boolean():
    def upper_lower_case_permutations(value):
        return tuple(
            "".join(x)
            for x in itertools.product(*zip(value.lower(), value.upper())))
    assert ensure_boolean(True) is True
    for s in upper_lower_case_permutations("yes"):
        assert ensure_boolean(s) is True
    for s in upper_lower_case_permutations("true"):
        assert ensure_boolean(s) is True
    assert ensure_boolean(False) is False
    for s in upper_lower_case_permutations("no"):
        assert ensure_boolean(s) is False
    for s in upper_lower_case_permutations("false"):
        assert ensure_boolean(s) is False
    with pytest.raises(InvalidIndexconfig):
        ensure_boolean(None)
        ensure_boolean("")
        ensure_boolean("foo")
        ensure_boolean([])
        ensure_boolean(["foo"])


def test_ensure_list():
    assert isinstance(ensure_list([]), list)
    assert isinstance(ensure_list(set()), list)
    assert isinstance(ensure_list(tuple()), list)
    assert ensure_list("foo") == ["foo"]
    assert ensure_list("foo,bar") == ["foo", "bar"]
    assert ensure_list(" foo , bar ") == ["foo", "bar"]
    with pytest.raises(InvalidIndexconfig):
        assert isinstance(ensure_list(None), list)
        assert isinstance(ensure_list(dict()), list)


def test_ensure_acl_list():
    assert isinstance(ensure_acl_list([]), list)
    assert isinstance(ensure_acl_list(set()), list)
    assert isinstance(ensure_acl_list(tuple()), list)
    assert ensure_acl_list("foo") == ["foo"]
    assert ensure_acl_list("foo,bar") == ["foo", "bar"]
    assert ensure_acl_list(" foo , bar ") == ["foo", "bar"]
    assert ensure_acl_list(" foo , bar ") == ["foo", "bar"]
    assert ensure_acl_list(" :anonymous: , FOO ,:AuTheNTicated: ") == [
        ":ANONYMOUS:", "FOO", ":AUTHENTICATED:"]
    with pytest.raises(InvalidIndexconfig):
        assert isinstance(ensure_acl_list(None), list)
        assert isinstance(ensure_acl_list(dict()), list)


@pytest.mark.parametrize(["input", "expected"], [
    ({},
     dict(type="stage")),

    ({"volatile": "foo"},
     InvalidIndexconfig),

    ({"volatile": True},
     dict(type="stage", volatile=True)),

    ({"volatile": "true"},
     dict(type="stage", volatile=True)),

    ({"volatile": "Yes"},
     dict(type="stage", volatile=True)),

    ({"volatile": False},
     dict(type="stage", volatile=False)),

    ({"volatile": "False"},
     dict(type="stage", volatile=False)),

    ({"volatile": "no"},
     dict(type="stage", volatile=False)),

    ({"volatile": "False", "bases": "root/pypi"},
     dict(type="stage", volatile=False, bases=("root/pypi",))),

    ({"volatile": "False", "bases": ["root/pypi"]},
     dict(type="stage", volatile=False, bases=("root/pypi",))),

    ({"volatile": "False", "bases": ["root/pypi"], "acl_upload": ["hello"]},
     dict(type="stage", volatile=False, bases=("root/pypi",),
          acl_upload=["hello"])),

    ({"volatile": "False", "bases": ["root/pypi"], "acl_toxresult_upload": ["hello"]},
     dict(type="stage", volatile=False, bases=("root/pypi",),
          acl_toxresult_upload=["hello"])),
])
def test_get_indexconfig_values(xom, input, expected):
    stage = PrivateStage(
        xom, "user", "index", {"type": "stage"}, StageCustomizer)
    if inspect.isclass(expected) and issubclass(expected, Exception):
        with pytest.raises(expected):
            stage.get_indexconfig_from_kwargs(**input)
    else:
        result = stage.get_indexconfig_from_kwargs(**input)
        assert result == expected
