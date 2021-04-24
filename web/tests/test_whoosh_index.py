from __future__ import unicode_literals
from devpi_web.indexing import ProjectIndexingInfo
import pytest


@pytest.mark.parametrize("input, expected", [
    ("Foo", [(0, 0, 3, "Foo")]),
    ("Foo Bar", [(0, 0, 3, "Foo"), (1, 4, 7, "Bar")]),
    ("Foo-Bar", [(0, 0, 3, "Foo"), (1, 4, 7, "Bar")]),
    ("Foo_Bar", [(0, 0, 3, "Foo"), (1, 4, 7, "Bar")]),
    ("1Foo Bar", [(0, 0, 4, "1Foo"), (1, 5, 8, "Bar")]),
    ("1Foo-Bar", [(0, 0, 4, "1Foo"), (1, 5, 8, "Bar")]),
    ("1Foo_Bar", [(0, 0, 4, "1Foo"), (1, 5, 8, "Bar")]),
    ("Foo 1Bar", [(0, 0, 3, "Foo"), (1, 4, 8, "1Bar")]),
    ("Foo-1Bar", [(0, 0, 3, "Foo"), (1, 4, 8, "1Bar")]),
    ("Foo_1Bar", [(0, 0, 3, "Foo"), (1, 4, 8, "1Bar")]),
    ("URLBar", [(0, 0, 6, "URLBar")]),
    ("BarURL", [(0, 0, 3, "Bar"), (1, 3, 6, "URL")]),
    ("FooBar", [(0, 0, 3, "Foo"), (1, 3, 6, "Bar")])])
def test_projectnametokenizer(input, expected):
    from devpi_web.whoosh_index import ProjectNameTokenizer
    tokenizer = ProjectNameTokenizer()
    assert [
        (x.pos, x.startchar, x.endchar, x.text)
        for x in tokenizer(input, positions=True, chars=True)] == expected


@pytest.mark.parametrize("input, expected", [
    (["devpi"], [
        "de", "dev", "devp",
        "ev", "evp", "evpi",
        "vp", "vpi", "pi"]),
    (["farglebargle"], [
        "fa", "far", "farg",
        "ar", "arg", "argl",
        "rg", "rgl", "rgle",
        "gl", "gle", "gleb",
        "le", "leb", "leba",
        "eb", "eba", "ebar",
        "ba", "bar", "barg",
        "ar", "arg", "argl",
        "rg", "rgl", "rgle",
        "gl", "gle", "le"]),
    (["Hello", "World"], [
        "He", "Hel", "Hell",
        "el", "ell", "ello",
        "ll", "llo", "lo",
        "Wo", "Wor", "Worl",
        "or", "orl", "orld",
        "rl", "rld", "ld"])])
def test_ngramfilter(input, expected):
    from devpi_web.whoosh_index import NgramFilter, Token
    nf = NgramFilter()
    token = Token()

    def tokens():
        for text in input:
            token.text = text
            yield token

    result = [(len(x.text), x.text, x.boost) for x in nf(tokens())]
    # three consecutive elements belong to the same position with different sizes
    # use a modified recipe from itertools docs for grouping
    size_groups = zip(*[iter(result)] * 3)
    for size_group in size_groups:
        # add the reverse index as second tuple item
        size_group = [
            (x[0], i, x[1], x[2])
            for i, x in zip(reversed(range(len(size_group))), size_group)]
        # now if we sort, longer and further to the beginning a ngram is, the
        # higher the boost
        size_group = sorted(size_group)
        ngrams = [x[2] for x in size_group]
        boosts = [x[3] for x in size_group]
        assert boosts[0] < boosts[1]
        assert boosts[1] < boosts[2]
        assert len(ngrams[0]) <= len(ngrams[1])
        assert len(ngrams[1]) <= len(ngrams[2])
    assert [x[1] for x in result] == expected


@pytest.mark.with_notifier
def test_search_after_register(mapp, testapp):
    from devpi_web.main import get_indexer
    indexer_thread = get_indexer(mapp.xom).indexer_thread
    mapp.xom.thread_pool.start_one(indexer_thread)
    api = mapp.create_and_use()
    mapp.set_versiondata({
        "name": "pkg1",
        "version": "2.6",
        "description": "foo"}, waithooks=True)
    indexer_thread.wait()
    r = testapp.get('/+search?query=foo', expect_errors=False)
    links = r.html.select('.searchresults a')
    assert [(l.text.strip(), l.attrs['href']) for l in links] == [
        ("pkg1-2.6", "http://localhost/%s/pkg1/2.6" % api.stagename),
        ("Description", "http://localhost/%s/pkg1/2.6#description" % api.stagename)]
    mapp.set_versiondata({
        "name": "pkg1",
        "version": "2.7",
        "description": "foo"}, waithooks=True)
    indexer_thread.wait()
    r = testapp.get('/+search?query=foo', expect_errors=False)
    links = r.html.select('.searchresults a')
    assert [(l.text.strip(), l.attrs['href']) for l in links] == [
        ("pkg1-2.7", "http://localhost/%s/pkg1/2.7" % api.stagename),
        ("Description", "http://localhost/%s/pkg1/2.7#description" % api.stagename)]
    r = testapp.xget(200, '/+search?query=foo')
    links = r.html.select('.searchresults a')
    assert [(l.text.strip(), l.attrs['href']) for l in links] == [
        ("pkg1-2.7", "http://localhost/%s/pkg1/2.7" % api.stagename),
        ("Description", "http://localhost/%s/pkg1/2.7#description" % api.stagename)]


def test_indexer_relative_path():
    from devpi_server.config import parseoptions, get_pluginmanager
    from devpi_server.main import Fatal
    from devpi_web.main import get_indexer_from_config
    options = ("--indexer-backend", "whoosh:path=ham")
    config = parseoptions(get_pluginmanager(), ("devpi-server",) + options)
    with pytest.raises(Fatal, match="must be absolute"):
        get_indexer_from_config(config)


@pytest.mark.nomocking
def test_dont_index_deleted_mirror(mapp, monkeypatch, simpypi, testapp):
    from devpi_web.main import get_indexer
    xom = mapp.xom
    indexer = get_indexer(xom)
    indexer_thread = indexer.indexer_thread
    calls = []
    monkeypatch.setattr(
        indexer, "_update_project",
        lambda *a, **kw: calls.append("update"))
    monkeypatch.setattr(
        indexer, "_delete_project",
        lambda *a, **kw: calls.append("delete"))
    simpypi.add_release("pkg", pkgver="pkg-1.0.zip")
    mapp.login("root", "")
    api = mapp.use("root/pypi")
    mapp.modify_index(
        "root/pypi",
        indexconfig=dict(type="mirror", mirror_url=simpypi.simpleurl, volatile=True))
    # fetching the index json triggers project names loading patched above
    r = testapp.get_json(api.index)
    assert r.status_code == 200
    assert r.json["result"]["type"] == "mirror"
    assert r.json["result"]["projects"] == ["pkg"]
    (link,) = mapp.getreleaseslist("pkg")
    assert "pkg-1.0.zip" in link
    r = testapp.delete(api.index)
    assert r.status_code == 201
    r = testapp.get_json(api.index)
    assert r.status_code == 404
    # so far no events should have run
    assert xom.keyfs.notifier.read_event_serial() == -1
    # now start the event handler thread
    xom.thread_pool.start_one(xom.keyfs.notifier)
    serial = xom.keyfs.get_current_serial()
    xom.keyfs.notifier.wait_event_serial(serial)
    assert xom.keyfs.notifier.read_event_serial() == serial
    # now start the indexer
    xom.thread_pool.start_one(indexer_thread)
    indexer_thread.wait()
    assert calls == ["delete"]


class FakeStage(object):
    def __init__(self, index_type):
        self.ixconfig = dict(type=index_type)
        self.name = index_type
        self.serials = {}
        self.serial = -1

    def get_last_project_change_serial_perstage(self, project, at_serial=None):
        return self.serials.get(project, self.serial)


class TestIndexingSharedData:
    @pytest.fixture
    def shared_data(self):
        from devpi_web.whoosh_index import IndexingSharedData
        return IndexingSharedData()

    def test_mirror_priority(self, shared_data):
        mirror = FakeStage('mirror')
        stage = FakeStage('stage')
        mirror_prj = ProjectIndexingInfo(stage=mirror, name='mirror_prj')
        stage_prj = ProjectIndexingInfo(stage=stage, name='stage_prj')
        result = []

        def handler(is_from_mirror, serial, indexname, names):
            (name,) = names
            result.append(name)
        # Regardless of the serial or add order, the stage should come first
        cases = [
            ((mirror_prj, 0), (stage_prj, 0)),
            ((mirror_prj, 1), (stage_prj, 0)),
            ((mirror_prj, 0), (stage_prj, 1)),
            ((stage_prj, 0), (mirror_prj, 0)),
            ((stage_prj, 1), (mirror_prj, 0)),
            ((stage_prj, 0), (mirror_prj, 1))]
        for (prj1, serial1), (prj2, serial2) in cases:
            shared_data.add(prj1, serial1)
            shared_data.add(prj2, serial2)
            assert shared_data.queue.qsize() == 2
            shared_data.process_next(handler)
            shared_data.process_next(handler)
            assert shared_data.queue.qsize() == 0
            assert result == ['stage_prj', 'mirror_prj']
            result.clear()

    @pytest.mark.parametrize("index_type", ["mirror", "stage"])
    def test_serial_priority(self, index_type, shared_data):
        stage = FakeStage(index_type)
        prj = ProjectIndexingInfo(stage=stage, name='prj')
        result = []

        def handler(is_from_mirror, serial, indexname, names):
            result.append(serial)

        # Later serials come first
        shared_data.add(prj, 1)
        shared_data.add(prj, 100)
        shared_data.add(prj, 10)
        assert shared_data.queue.qsize() == 3
        shared_data.process_next(handler)
        shared_data.process_next(handler)
        shared_data.process_next(handler)
        assert shared_data.queue.qsize() == 0
        assert result == [100, 10, 1]

    def test_error_queued(self, shared_data):
        stage = FakeStage('stage')
        prj = ProjectIndexingInfo(stage=stage, name='prj')

        next_ts_result = []
        handler_result = []
        orig_next_ts = shared_data.next_ts

        def next_ts(delay):
            next_ts_result.append(delay)
            return orig_next_ts(delay)
        shared_data.next_ts = next_ts

        def handler(is_from_mirror, serial, indexname, names):
            (name,) = names
            handler_result.append(name)
            raise ValueError

        # No waiting on empty queues
        shared_data.QUEUE_TIMEOUT = 0
        shared_data.add(prj, 0)
        assert shared_data.queue.qsize() == 1
        assert shared_data.error_queue.qsize() == 0
        assert next_ts_result == []
        assert handler_result == []
        # An exception puts the info into the error queue
        shared_data.process_next(handler)
        assert shared_data.queue.qsize() == 0
        assert shared_data.error_queue.qsize() == 1
        assert next_ts_result == [11]
        assert handler_result == ['prj']
        # Calling again doesn't change anything,
        # because there is a delay on errors
        shared_data.process_next(handler)
        assert shared_data.queue.qsize() == 0
        assert shared_data.error_queue.qsize() == 1
        assert next_ts_result == [11]
        assert handler_result == ['prj']
        # When removing the delay check, the handler is called again and the
        # info re-queued with a longer delay
        shared_data.is_in_future = lambda ts: False
        shared_data.process_next(handler)
        assert shared_data.queue.qsize() == 0
        assert shared_data.error_queue.qsize() == 1
        assert next_ts_result == [11, 11 * shared_data.ERROR_QUEUE_DELAY_MULTIPLIER]
        assert handler_result == ['prj', 'prj']
        while 1:
            # The delay is increased until reaching a maximum
            shared_data.process_next(handler)
            delay = next_ts_result[-1]
            if delay >= shared_data.ERROR_QUEUE_MAX_DELAY:
                break
        # then it will stay there
        shared_data.process_next(handler)
        delay = next_ts_result[-1]
        assert delay == shared_data.ERROR_QUEUE_MAX_DELAY
        # The number of retries should be reasonable.
        # Needs adjustment in case the ERROR_QUEUE_DELAY_MULTIPLIER
        # or ERROR_QUEUE_MAX_DELAY is changed
        assert len(next_ts_result) == 17
        assert len(handler_result) == 17

    def test_extend_differing_stage(self, shared_data):
        mirror = FakeStage('mirror')
        stage = FakeStage('stage')
        mirror_prj = ProjectIndexingInfo(stage=mirror, name='mirror_prj')
        stage_prj = ProjectIndexingInfo(stage=stage, name='stage_prj')
        with pytest.raises(ValueError, match="Project isn't from same index"):
            shared_data.extend([mirror_prj, stage_prj], 0)

    def test_extend_max_names(self, shared_data):
        shared_data.QUEUE_MAX_NAMES = 3
        mirror = FakeStage('mirror')
        prjs = []
        for i in range(10):
            prjs.append(ProjectIndexingInfo(stage=mirror, name='prj%d' % i))

        result = []

        def handler(is_from_mirror, serial, indexname, names):
            result.append(names)

        shared_data.extend(prjs, 0)
        assert shared_data.queue.qsize() == 4

        shared_data.process_next(handler)
        assert shared_data.queue.qsize() == 3
        assert result == [
            ['prj0', 'prj1', 'prj2']]
        shared_data.process_next(handler)
        assert shared_data.queue.qsize() == 2
        assert result == [
            ['prj0', 'prj1', 'prj2'],
            ['prj3', 'prj4', 'prj5']]
        shared_data.process_next(handler)
        assert shared_data.queue.qsize() == 1
        assert result == [
            ['prj0', 'prj1', 'prj2'],
            ['prj3', 'prj4', 'prj5'],
            ['prj6', 'prj7', 'prj8']]
        shared_data.process_next(handler)
        assert shared_data.queue.qsize() == 0
        assert result == [
            ['prj0', 'prj1', 'prj2'],
            ['prj3', 'prj4', 'prj5'],
            ['prj6', 'prj7', 'prj8'],
            ['prj9']]
        assert shared_data.error_queue.qsize() == 0

    def test_queue_projects_max_names(self, shared_data):
        shared_data.QUEUE_MAX_NAMES = 3
        mirror = FakeStage('mirror')
        mirror.serial = 0
        prjs = []
        for i in range(10):
            prjs.append(ProjectIndexingInfo(stage=mirror, name='prj%d' % i))

        result = []

        def handler(is_from_mirror, serial, indexname, names):
            result.append(names)

        class FakeSearcher:
            def document_number(self, path):
                return None

        shared_data.queue_projects(prjs, 0, FakeSearcher())
        assert shared_data.queue.qsize() == 4

        shared_data.process_next(handler)
        assert shared_data.queue.qsize() == 3
        assert result == [
            ['prj0', 'prj1', 'prj2']]
        shared_data.process_next(handler)
        assert shared_data.queue.qsize() == 2
        assert result == [
            ['prj0', 'prj1', 'prj2'],
            ['prj3', 'prj4', 'prj5']]
        shared_data.process_next(handler)
        assert shared_data.queue.qsize() == 1
        assert result == [
            ['prj0', 'prj1', 'prj2'],
            ['prj3', 'prj4', 'prj5'],
            ['prj6', 'prj7', 'prj8']]
        shared_data.process_next(handler)
        assert shared_data.queue.qsize() == 0
        assert result == [
            ['prj0', 'prj1', 'prj2'],
            ['prj3', 'prj4', 'prj5'],
            ['prj6', 'prj7', 'prj8'],
            ['prj9']]
        assert shared_data.error_queue.qsize() == 0

    def test_queue_projects_skip_existing(self, shared_data):
        """ For projects from mirrors the existing serial from the index
            is checked to skip reindexing projects which are already up to
            date.

            There was a bug where the used serial was overwritten during that
            check causing wrong entries in the queue.
        """
        class FakeSearcher:
            index = {}

            def document_number(self, path):
                if path in self.index:
                    return path

            def stored_fields(self, path):
                return {'serial': self.index[path]}

        searcher = FakeSearcher()

        result = []

        def handler(is_from_mirror, serial, indexname, names):
            if is_from_mirror and indexname == 'mirror':
                for project in names:
                    searcher.index['/%s/%s' % (indexname, project)] = serial
            result.append((is_from_mirror, serial, indexname, names))

        mirror = FakeStage('mirror')
        stage = FakeStage('stage')
        # add one project on the mirror at serial 0
        mirror.serials['mirror1'] = 0
        shared_data.queue_projects(
            [
                ProjectIndexingInfo(stage=mirror, name='mirror1')],
            0, searcher)
        assert shared_data.queue.qsize() == 1
        while shared_data.queue.qsize():
            shared_data.process_next(handler)
        assert result == [
            (True, 0, 'mirror', ['mirror1'])]
        result.clear()
        # add another project on the mirror at serial 1 and re-add first project
        mirror.serials['mirror2'] = 1
        shared_data.queue_projects(
            [
                ProjectIndexingInfo(stage=mirror, name='mirror1'),
                ProjectIndexingInfo(stage=mirror, name='mirror2')],
            1, searcher)
        assert shared_data.queue.qsize() == 1
        while shared_data.queue.qsize():
            shared_data.process_next(handler)
        assert result == [
            (True, 1, 'mirror', ['mirror2'])]
        result.clear()
        # add a project on the stage at serial 2 and re-add mirror projects
        stage.serials['prj'] = 2
        shared_data.queue_projects(
            [
                ProjectIndexingInfo(stage=mirror, name='mirror1'),
                ProjectIndexingInfo(stage=mirror, name='mirror2'),
                ProjectIndexingInfo(stage=stage, name='prj')],
            2, searcher)
        assert shared_data.queue.qsize() == 1
        while shared_data.queue.qsize():
            shared_data.process_next(handler)
        assert result == [
            (False, 2, 'stage', ('prj',))]
        result.clear()
        # now re-add everything at a later serial
        shared_data.queue_projects(
            [
                ProjectIndexingInfo(stage=mirror, name='mirror1'),
                ProjectIndexingInfo(stage=mirror, name='mirror2'),
                ProjectIndexingInfo(stage=stage, name='prj')],
            3, searcher)
        assert shared_data.queue.qsize() == 1
        while shared_data.queue.qsize():
            shared_data.process_next(handler)
        assert result == [
            (False, 3, 'stage', ('prj',))]
        result.clear()
