from __future__ import unicode_literals
from collections import defaultdict
from devpi_common.validation import normalize_name
from devpi_server.log import threadlog as log
from devpi_server.log import thread_push_log
from devpi_server.main import fatal
from devpi_server.readonly import get_mutable_deepcopy
from devpi_server import mythread
from devpi_web.indexing import iter_projects
from devpi_web.indexing import ProjectIndexingInfo
from devpi_web.indexing import is_project_cached
from devpi_web.indexing import preprocess_project
from devpi_web.main import get_indexer
from pluggy import HookimplMarker
from whoosh import fields
from whoosh.analysis import Filter, LowercaseFilter, RegexTokenizer
from whoosh.analysis import Token, Tokenizer
from whoosh.compat import text_type, u
from whoosh.highlight import ContextFragmenter, HtmlFormatter, highlight
from whoosh.index import create_in, exists_in, open_dir
from whoosh.index import IndexError as WhooshIndexError
from whoosh.qparser import QueryParser
from whoosh.qparser import plugins
from whoosh.searching import ResultsPage
from whoosh.util.text import rcompile
import itertools
import os
import py
import shutil
import sys
import time
import traceback


hookimpl = HookimplMarker("devpiweb")
devpiserver_hookimpl = HookimplMarker("devpiserver")


try:
    xrange
except NameError:
    xrange = range


class ProjectNameTokenizer(Tokenizer):
    def __init__(self):
        self.expression = rcompile(r'(\W|_)')

    def __eq__(self, other):
        if self.__class__ is other.__class__:
            if self.expression.pattern == other.expression.pattern:
                return True
        return False

    def iter_value(self, value):
        current = ''
        prev = ''
        pos = 0
        match = self.expression.match
        for i, c in enumerate(value):
            if match(c):
                yield pos, i, current
                current = ''
                pos = i + 1
                prev = ''
                continue
            if c.upper() == c:
                if prev.upper() != prev:
                    yield pos, i, current
                    current = c
                    pos = i
                    prev = c
                    continue
            prev = c
            current += c
        yield pos, i + 1, current

    def __call__(self, value, positions=False, chars=False, keeporiginal=False,
                 removestops=True, start_pos=0, start_char=0, tokenize=True,
                 mode='', **kwargs):
        assert isinstance(value, text_type), "%s is not unicode" % repr(value)

        t = Token(positions, chars, removestops=removestops, mode=mode,
                  **kwargs)
        if not tokenize:
            t.original = t.text = value
            t.boost = 1.0
            if positions:
                t.pos = start_pos
            if chars:
                t.startchar = start_char
                t.endchar = start_char + len(value)
            yield t
        else:
            for pos, (start, stop, text) in enumerate(self.iter_value(value)):
                t.text = text
                t.boost = 1.0
                if keeporiginal:
                    t.original = t.text
                t.stopped = False
                if positions:
                    t.pos = start_pos + pos
                if chars:
                    t.startchar = start_char + start
                    t.endchar = start_char + stop
                yield t


def project_name(name, tokenizer=ProjectNameTokenizer()):
    result = []
    if "-" in name:
        result.append(name.replace("-", "_"))
    result.extend(x[2] for x in tokenizer.iter_value(name))
    return ' '.join(result)


class NgramFilter(Filter):
    """Splits token text into N-grams.

    >>> rext = RegexTokenizer()
    >>> stream = rext("hello there")
    >>> ngf = NgramFilter(4)
    >>> [token.text for token in ngf(stream)]
    ["hell", "ello", "ther", "here"]
    """

    __inittypes__ = dict(minsize=int, maxsize=int)

    def __init__(self):
        """
        :param minsize: The minimum size of the N-grams.
        :param maxsize: The maximum size of the N-grams. If you omit this
            parameter, maxsize == minsize.
        :param at: If 'start', only take N-grams from the start of each word.
            if 'end', only take N-grams from the end of each word. Otherwise,
            take all N-grams from the word (the default).
        """

        self.min = 2
        self.max = 4

    def __eq__(self, other):
        return other and self.__class__ is other.__class__\
            and self.min == other.min and self.max == other.max

    def __call__(self, tokens):
        assert hasattr(tokens, "__iter__")
        for t in tokens:
            text = t.text
            len_text = len(text)
            if len_text < self.min:
                continue
            size_weight_base = 0.25 / len_text

            chars = t.chars
            if chars:
                startchar = t.startchar
            # Token positions don't mean much for N-grams,
            # so we'll leave the token's original position
            # untouched.

            if t.mode == "query":
                size = min(self.max, len(t.text))
                for start in xrange(0, len_text - size + 1):
                    t.text = text[start:start + size]
                    if chars:
                        t.startchar = startchar + start
                        t.endchar = startchar + start + size
                    yield t
            else:
                for start in xrange(0, len_text - self.min + 1):
                    for size in xrange(self.min, self.max + 1):
                        end = start + size
                        if end > len_text:
                            continue

                        t.text = text[start:end]

                        if chars:
                            t.startchar = startchar + start
                            t.endchar = startchar + end

                        # boost ngrams at start of words and ones closer to
                        # the original length of the word
                        pos_weight = 0.05 / end * (end - start)
                        size_weight = size_weight_base * size
                        t.boost = 1.0 + pos_weight + size_weight
                        yield t


def NgramWordAnalyzer():
    return RegexTokenizer() | LowercaseFilter() | NgramFilter()


class SearchUnavailableException(Exception):
    pass


def update_schema(ix, schema):
    if ix.schema == schema:
        return
    existing_names = set(ix.schema.names())
    schema_names = set(schema.names())
    removed_names = existing_names - schema_names
    added_names = schema_names - existing_names
    if not (removed_names or added_names):
        return
    writer = ix.writer()
    for name in removed_names:
        writer.remove_field(name)
    for name in added_names:
        writer.add_field(name, schema[name])
    log.warn(
        "The search index schema has changed. "
        "The update can take a while depending on the size of your index.")
    if removed_names:
        writer.commit(optimize=True)
    else:
        writer.commit()


class IndexingSharedData(object):
    QUEUE_MAX_NAMES = 2500
    QUEUE_TIMEOUT = 1
    ERROR_QUEUE_DELAY_MULTIPLIER = 1.5
    ERROR_QUEUE_MAX_DELAY = 60 * 60

    def __init__(self):
        try:
            from queue import Empty, PriorityQueue
        except ImportError:
            from Queue import Empty, PriorityQueue
        self.Empty = Empty
        self.queue = PriorityQueue()
        self.error_queue = PriorityQueue()
        self.last_added = None
        self.last_errored = None
        self.last_processed = None

    def add(self, project, serial):
        # note the negated serial for the PriorityQueue
        self.queue.put((
            project.is_from_mirror,
            -serial,
            project.indexname,
            (project.name,)))
        self.last_added = time.time()

    def next_ts(self, delay):
        return time.time() + delay

    def add_errored(self, is_from_mirror, serial, indexname, names, ts=None, delay=11):
        if ts is None:
            ts = self.next_ts(delay)
        # this priority queue is ordered by time stamp
        self.error_queue.put(
            (ts, delay, is_from_mirror, serial, indexname, names))
        self.last_errored = time.time()

    def extend(self, projects, serial):
        if not projects:
            return
        names = []
        is_from_mirror = projects[0].is_from_mirror
        indexname = projects[0].indexname
        for project in projects:
            differs = (
                project.is_from_mirror != is_from_mirror
                or project.indexname != indexname)
            if differs:
                raise ValueError("Project isn't from same index")
        for project in projects:
            names.append(project.name)
            if len(names) >= self.QUEUE_MAX_NAMES:
                self.queue.put((is_from_mirror, -serial, indexname, names))
                self.last_added = time.time()
                names = []
        if names:
            # note the negated serial for the PriorityQueue
            self.queue.put((is_from_mirror, -serial, indexname, names))
            self.last_added = time.time()

    def queue_projects(self, projects, at_serial, searcher):
        log.debug("Queuing projects for index update")
        queued_counter = itertools.count()
        queued = next(queued_counter)
        last_time = time.time()
        mirror_projects = {}
        processed = 0
        for processed, project in enumerate(projects, start=1):
            if time.time() - last_time > 5:
                last_time = time.time()
                log.debug(
                    "Processed a total of %s projects and queued %s so far. "
                    "Currently in %s" % (processed, queued, project.indexname))
            if project.is_from_mirror:
                # we find the last serial the project was changed to avoid re-indexing
                project_serial = project.stage.get_last_project_change_serial_perstage(
                    project.name, at_serial=at_serial)
                # mirrors have no docs, so we can shortcut
                path = '/%s/%s' % (project.indexname, project.name)
                existing = None
                doc_num = searcher.document_number(path=path)
                if doc_num is not None:
                    existing = searcher.stored_fields(doc_num)
                if existing:
                    existing_serial = existing.get('serial', -1)
                    if existing_serial >= project_serial:
                        continue
                # we use at_serial here, because indexing is always done
                # with the latest metadata
                key = (project.indexname, at_serial)
                _projects = mirror_projects.setdefault(key, [])
                _projects.append(project)
                if len(_projects) >= self.QUEUE_MAX_NAMES:
                    self.extend(_projects, at_serial)
                    _projects.clear()
            else:
                # private projects need to be checked in IndexerThread.handler,
                # because preprocess_project might depend on files which were
                # not available when indexing while replicating like doczips
                self.add(project, at_serial)
            queued = next(queued_counter)
        for (indexname, serial), _projects in mirror_projects.items():
            self.extend(_projects, serial)
        log.info("Processed a total of %s projects and queued %s" % (processed, queued))

    def is_in_future(self, ts):
        return ts > time.time()

    def process_next_errored(self, handler):
        try:
            # it seems like without the timeout this isn't triggered frequent
            # enough, the thread was waiting a long time even though there
            # were already/still items in the queue
            info = self.error_queue.get(timeout=self.QUEUE_TIMEOUT)
        except self.Empty:
            return
        (ts, delay, is_from_mirror, serial, indexname, names) = info
        try:
            if self.is_in_future(ts):
                # not current yet, so re-add it
                self.add_errored(
                    is_from_mirror, serial, indexname, names,
                    ts=ts, delay=delay)
                return
            handler(is_from_mirror, serial, indexname, names)
        except Exception:
            # another failure, re-add with longer delay
            self.add_errored(
                is_from_mirror, serial, indexname, names,
                delay=min(
                    delay * self.ERROR_QUEUE_DELAY_MULTIPLIER,
                    self.ERROR_QUEUE_MAX_DELAY))
        finally:
            self.error_queue.task_done()
            self.last_processed = time.time()

    def process_next(self, handler):
        try:
            # it seems like without the timeout this isn't triggered frequent
            # enough, the thread was waiting a long time even though there
            # were already/still items in the queue
            info = self.queue.get(timeout=self.QUEUE_TIMEOUT)
        except self.Empty:
            # when the regular queue is empty, we retry previously errored ones
            return self.process_next_errored(handler)
        (is_from_mirror, serial, indexname, names) = info
        # negate again, because it was negated for the PriorityQueue
        serial = -serial
        try:
            handler(is_from_mirror, serial, indexname, names)
        except Exception:
            (exc_type, exc_value, exc_traceback) = sys.exc_info()
            (filename, lineno, name) = traceback.extract_tb(exc_traceback, 2)[-1][:3]
            del exc_traceback
            formatted_exception = ''.join(
                traceback.format_exception_only(exc_type, exc_value)).strip()
            log.warn(
                "Error during indexing in %s:%s:%s %s" % (
                    filename, lineno, name, formatted_exception))
            self.add_errored(is_from_mirror, serial, indexname, names)
        finally:
            self.queue.task_done()
            self.last_processed = time.time()

    def wait(self, error_queue=False):
        self.queue.join()
        if error_queue:
            self.error_queue.join()


class IndexerThread(object):
    def __init__(self, xom, shared_data):
        self.xom = xom
        self.shared_data = shared_data

    def wait(self, error_queue=False):
        self.shared_data.wait(error_queue=error_queue)

    def handler(self, is_from_mirror, serial, indexname, names):
        log.debug(
            "Got %s projects from %s at serial %s for indexing",
            len(names), indexname, serial)
        ix = get_indexer(self.xom)
        counter = itertools.count()
        project_ix = ix.get_project_ix()
        main_keys = project_ix.schema.names()
        writer = project_ix.writer()
        searcher = project_ix.searcher()
        try:
            with self.xom.keyfs.transaction(write=False) as tx:
                stage = self.xom.model.getstage(indexname)
                if stage is not None:
                    for name in names:
                        data = preprocess_project(
                            ProjectIndexingInfo(stage=stage, name=name))
                        if data is None:
                            ix._delete_project(
                                indexname, name, tx.at_serial, counter, writer,
                                searcher=searcher)
                            continue
                        # because we use the current transaction, we also
                        # use the current serial for indexing
                        ix._update_project(
                            data, tx.at_serial, counter, main_keys, writer,
                            searcher=searcher)
                else:
                    # stage was deleted
                    for name in names:
                        ix._delete_project(
                            indexname, name, tx.at_serial, counter, writer,
                            searcher=searcher)
            count = next(counter)
        except Exception:
            writer.cancel()
            # let the queue handle retries
            raise
        else:
            if count:
                log.info("Committing %s new documents to search index." % count)
            else:
                log.debug("Committing no new documents to search index.")
            writer.commit()

    def tick(self):
        self.shared_data.process_next(self.handler)

    def thread_run(self):
        thread_push_log("[IDX]")
        last_time = time.time()
        event_serial = None
        serial = -1
        while 1:
            try:
                if time.time() - last_time > 5:
                    last_time = time.time()
                    size = self.shared_data.queue.qsize()
                    if size:
                        log.info("Indexer queue size ~ %s" % size)
                    event_serial = self.xom.keyfs.notifier.read_event_serial()
                    serial = self.xom.keyfs.get_current_serial()
                if event_serial is not None and event_serial < serial:
                    # be nice to everything else
                    self.thread.sleep(1.0)
                self.tick()
            except mythread.Shutdown:
                raise
            except Exception:
                log.exception(
                    "Unhandled exception in indexer thread.")
                self.thread.sleep(1.0)


class InitialQueueThread(object):
    def __init__(self, xom, shared_data):
        self.xom = xom
        self.shared_data = shared_data

    def thread_run(self):
        thread_push_log("[IDXQ]")
        with self.xom.keyfs.transaction(write=False) as tx:
            indexer = get_indexer(self.xom)
            searcher = indexer.get_project_ix().searcher()
            self.shared_data.queue_projects(
                iter_projects(self.xom), tx.at_serial, searcher)


def setup_thread(xom):
    indexer_thread = getattr(xom, 'whoosh_indexer_thread', None)
    if indexer_thread is None:
        shared_data = IndexingSharedData()
        indexer_thread = IndexerThread(xom, shared_data)
        xom.whoosh_indexer_thread = indexer_thread
        if not getattr(xom.config.args, 'requests_only', None):
            xom.thread_pool.register(xom.whoosh_indexer_thread)
            xom.thread_pool.register(InitialQueueThread(xom, shared_data))
    return indexer_thread


class Index(object):
    SearchUnavailableException = SearchUnavailableException

    def __init__(self, config, settings):
        if 'path' not in settings:
            index_path = config.serverdir.join('.indices')
        else:
            index_path = settings['path']
            if not os.path.isabs(index_path):
                fatal("The path for Whoosh index files must be absolute.")
            index_path = py.path.local(index_path)
        index_path.ensure_dir()
        log.info("Using %s for Whoosh index files." % index_path)
        self.index_path = index_path.strpath
        self.indexer_thread = None
        self.shared_data = None
        self.xom = None

    def runtime_setup(self, xom):
        self.xom = xom
        self.indexer_thread = setup_thread(xom)
        self.shared_data = self.indexer_thread.shared_data

    def ix(self, name):
        schema = getattr(self, '%s_schema' % name)
        if not exists_in(self.index_path, indexname=name):
            return create_in(self.index_path, schema, indexname=name)
        ix = open_dir(self.index_path, indexname=name)
        update_schema(ix, schema)
        return ix

    def delete_index(self):
        shutil.rmtree(self.index_path)

    def needs_reindex(self):
        project_ix = self.get_project_ix()
        if project_ix.is_empty():
            return True
        return project_ix.schema != self.project_schema

    def get_project_ix(self):
        return self.ix('project')

    @property
    def project_schema(self):
        return fields.Schema(
            path=fields.ID(stored=True, unique=True),
            name=fields.ID(stored=True),
            user=fields.ID(stored=True),
            index=fields.ID(stored=True),
            serial=fields.NUMERIC(stored=True),
            classifiers=fields.KEYWORD(commas=True, scorable=True),
            keywords=fields.KEYWORD(stored=True, commas=False, scorable=True),
            version=fields.STORED(),
            doc_version=fields.STORED(),
            type=fields.ID(stored=True),
            text_path=fields.STORED(),
            text_title=fields.STORED(),
            text=fields.TEXT(analyzer=NgramWordAnalyzer(), stored=False, phrase=False))

    def _delete_project(self, indexname, project, serial, counter, writer, searcher):
        path = u"/%s/%s" % (indexname, project)
        writer.delete_by_term('path', path, searcher=searcher)
        next(counter)
        log.debug("Removed %s from search index.", path)

    def delete_projects(self, projects):
        # we just queue the projects and let the thread handle this
        self.update_projects(projects)

    def _update_project(self, project, serial, counter, main_keys, writer, searcher):
        def add_document(**kw):
            try:
                writer.add_document(**kw)
            except Exception:
                log.exception("Exception while trying to add the following data to the search index:\n%r" % kw)
                raise

        text_keys = (
            ('author', 0.5),
            ('author_email', 0.5),
            ('description', 1.5),
            ('summary', 1.75),
            ('keywords', 1.75))
        data = dict((u(x), get_mutable_deepcopy(project[x])) for x in main_keys if x in project)
        data['path'] = u"/{user}/{index}/{name}".format(
            user=data['user'], index=data['index'],
            name=normalize_name(data['name']))
        existing = None
        doc_num = searcher.document_number(path=data['path'])
        if doc_num is not None:
            existing = searcher.stored_fields(doc_num)
        if existing is not None:
            needs_reindex = False
            if ('+doczip' in project) != ('doc_version' in existing):
                needs_reindex = True
            existing_serial = existing.get('serial', -1)
            if existing_serial < serial:
                needs_reindex = True
            if not needs_reindex:
                return
        # because we use hierarchical documents, we have to delete
        # everything we got for this path and index it again
        writer.delete_by_term('path', data['path'], searcher=searcher)
        data['serial'] = serial
        data['type'] = "project"
        data['text'] = "%s %s" % (data['name'], project_name(data['name']))
        with writer.group():
            add_document(**data)
            next(counter)
            for key, boost in text_keys:
                if key not in project:
                    continue
                add_document(**{
                    "path": data['path'],
                    "type": key,
                    "text": project[key],
                    "_text_boost": boost})
                next(counter)
            if '+doczip' not in project:
                return
            if not project['+doczip'].exists():
                log.error("documentation zip file is missing %s", data['path'])
                return
            for page in project['+doczip'].values():
                if page is None:
                    continue
                add_document(**{
                    "path": data['path'],
                    "type": "title",
                    "text": page['title'],
                    "text_path": page['path'],
                    "text_title": page['title']})
                next(counter)
                add_document(**{
                    "path": data['path'],
                    "type": "page",
                    "text": page['text'],
                    "text_path": page['path'],
                    "text_title": page['title']})
                next(counter)

    def update_projects(self, projects, clear=False):
        project_ix = self.get_project_ix()
        self.shared_data.queue_projects(
            projects, self.xom.keyfs.tx.at_serial, project_ix.searcher())

    def _process_results(self, raw, page=1):
        items = []
        result_info = dict()
        result = {"items": items, "info": result_info}
        found = raw.scored_length()
        result_info['found'] = found
        if isinstance(raw, ResultsPage):
            result_info['total'] = raw.total
            result_info['pagecount'] = raw.pagecount
            result_info['pagenum'] = raw.pagenum
            results = raw.results
        else:
            results = raw
        collapsed_counts = defaultdict(int)
        result_info['collapsed_counts'] = collapsed_counts
        fields = set(x.field() for x in results.q.leaves())
        collapse = "path" not in fields
        parents = {}
        text_field = results.searcher.schema['text']
        for item in raw:
            info = {
                "data": dict(item),
                "words": frozenset(
                    text_field.from_bytes(term[1])
                    for term in item.matched_terms()
                    if term[0] == 'text')}
            for attr in ('docnum', 'pos', 'rank', 'score'):
                info[attr] = getattr(item, attr)
            path = item['path']
            if path in parents:
                parent = parents[path]
            elif info['data'].get('type') == 'project':
                parent = parents[path] = dict(info)
                parent['sub_hits'] = []
                items.append(parent)
            else:
                parent = {
                    "data": item.searcher.document(path=path),
                    "sub_hits": []}
                parents[path] = parent
                items.append(parent)
            if collapse and len(parent['sub_hits']) > 3:
                collapsed_counts[path] = collapsed_counts[path] + 1
            else:
                parent['sub_hits'].append(info)
        return result

    def _search_projects(self, searcher, query, page=1):
        if page is None:
            result = searcher.search(query, limit=None, terms=True)
        else:
            result = searcher.search_page(query, page, terms=True)
        return result

    @property
    def _query_parser_help(self):
        field_docs = dict(
            classifiers="""
                The <a href="https://pypi.org/pypi?%3Aaction=list_classifiers" target="_blank">trove classifiers</a> of a package.
                Use single quotes to specify a classifier, as they contain spaces:
                <code>classifiers:'Programming Language :: Python :: 3'</code>""",
            index="The name of the index. This is only the name part, without the user. For example: <code>index:pypi</code>",
            keywords="The keywords of a package.",
            name="The package name. For example: <code>name:devpi-client</code>",
            path="The path of the package in the form '/{user}/{index}/{name}'.  For example: <code>path:/root/pypi/devpi-server</code>",
            text=None,
            type="""
                The type of text.
                One of <code>project</code> for the project name,
                <code>title</code> for the title of a documentation page,
                <code>page</code> for a documentation page,
                or one of the following project metadata fields:
                <code>author</code>, <code>author_email</code>,
                <code>description</code>, <code>keywords</code>,
                <code>summary</code>. For example: <code>type:page</code>
                """,
            user="The user name.")
        schema = self.project_schema
        fields = []
        for name in schema.names():
            field = schema[name]
            if not field.indexed:
                continue
            if name not in field_docs:
                fields.append((name, "Undocumented"))
                continue
            field_doc = field_docs[name]
            if field_doc is None:
                continue
            fields.append((name, field_doc))
        fields_doc = "<dl>%s</dl>" % ''.join("<dt><code>%s</code></dt><dd>%s</dd>" % x for x in fields)
        return {
            plugins.WhitespacePlugin:
                None,
            plugins.SingleQuotePlugin: """
                To specify a term which contains spaces, use single quotes like this:
                <code>'term with spaces'</code>""",
            plugins.FieldsPlugin: """
                By using a search like <code>fieldname:term</code>,
                you can search in the following fields:<br />%s""" % fields_doc,
            plugins.PrefixPlugin: """
                End a term with an asterisk to search by prefix like this: <code>path:/fschulze/*</code>""",
            plugins.GroupPlugin: """
                Group query clauses with parentheses.""",
            plugins.OperatorsPlugin: """
                Use the <code>AND</code>, <code>OR</code>,
                <code>ANDNOT</code>, <code>ANDMAYBE</code>, and <code>NOT</code><br />
                operators to further refine your search.<br />
                Write them in all capital letters, otherwise they will be interpreted as search terms.<br />
                An example search would be: <code>devpi ANDNOT client</code>""",
            plugins.BoostPlugin: """
                Boost a term by adding a circumflex followed by the boost value like this:
                <code>term^2</code>"""}

    def _query_parser_plugins(self):
        return [
            plugins.WhitespacePlugin(),
            plugins.SingleQuotePlugin(),
            plugins.FieldsPlugin(),
            plugins.PrefixPlugin(),
            plugins.GroupPlugin(),
            plugins.OperatorsPlugin(),
            plugins.BoostPlugin()]

    def _query_projects(self, searcher, querystring, page=1):
        parser = QueryParser(
            "text", self.project_schema,
            plugins=self._query_parser_plugins())
        query = parser.parse(querystring)
        return self._search_projects(searcher, query, page=page)

    def search_projects(self, query, page=1):
        searcher = self.get_project_ix().searcher()
        try:
            result = self._process_results(
                self._search_projects(searcher, query, page=page))
        except (OSError, WhooshIndexError) as e:
            raise SearchUnavailableException(e)
        else:
            searcher.close()
            return result

    def query_projects(self, querystring, page=1):
        searcher = self.get_project_ix().searcher()
        try:
            result = self._process_results(
                self._query_projects(searcher, querystring, page=page))
        except (OSError, WhooshIndexError) as e:
            raise SearchUnavailableException(e)
        else:
            searcher.close()
            return result

    def _search_packages(self, query, sro):
        result = self.query_projects(query, page=None)
        # first gather basic info and only get most relevant info based on
        # stage resolution order
        stagename2order = {x.name: i for i, x in enumerate(sro)}
        stagename2stage = {x.name: x for x in sro}
        name2stage = {}
        name2data = {}
        for item in result['items']:
            data = item['data']
            (user, index, name) = data['path'][1:].split('/')
            stage = stagename2stage.get('%s/%s' % (user, index))
            if stage is None:
                continue
            current_stage = name2stage.get(name)
            if current_stage is None or stagename2order[stage.name] < stagename2order[current_stage.name]:
                name2stage[name] = stage
                try:
                    score = item['score']
                except KeyError:
                    score = False
                    sub_hits = item.get('sub_hits')
                    if sub_hits:
                        score = sub_hits[0].get('score', False)
                name2data[name] = dict(
                    version=data.get('version', ''),
                    score=score)
        # then gather more info if available and build results
        hits = []
        for name, stage in name2stage.items():
            data = name2data[name]
            version = data['version']
            summary = '[%s]' % stage.name
            if version and is_project_cached(stage, name):
                metadata = stage.get_versiondata(name, version)
                version = metadata.get('version', version)
                summary += ' %s' % metadata.get('summary', '')
            hits.append(dict(
                name=name, summary=summary,
                version=version, _pypi_ordering=data['score']))
        return hits

    def _querystring(self, searchinfo):
        fields = searchinfo['fields']
        operator = searchinfo['operator'].upper()
        if operator not in ('AND', 'OR', 'ANDNOT', 'ANDMAYBE', 'NOT'):
            raise ValueError("Unknown operator '%s'." % operator)
        if set(fields.keys()).difference(['name', 'summary']):
            raise ValueError("Only 'name' and 'summary' allowed in query.")
        parts = []
        for key, field in (('name', 'project'), ('summary', 'summary')):
            value = fields.get(key, [])
            if len(value) == 0:
                continue
            elif len(value) == 1:
                parts.append('(type:%s "%s")' % (field, value[0].replace('"', '')))
            else:
                raise ValueError("Only one value allowed for query.")
        querystring = (" %s " % operator).join(parts)
        log.debug("_querystring {0}".format(querystring))
        return querystring

    def query_packages(self, searchinfo, sro):
        return self._search_packages(self._querystring(searchinfo), sro)

    def get_query_parser_html_help(self):
        result = []
        query_parser_help = self._query_parser_help
        for plugin in self._query_parser_plugins():
            if plugin.__class__ not in query_parser_help:
                result.append(
                    "Undocumented query plugin '%s'.<br />%s" % (
                        plugin.__class__.__name__, plugin.__doc__))
                continue
            docs = query_parser_help[plugin.__class__]
            if docs is None:
                continue
            result.append(docs)
        return result

    def highlight(self, text, words):
        fragmenter = ContextFragmenter()
        formatter = HtmlFormatter()
        analyzer = self.project_schema['text'].analyzer
        return highlight(text, words, analyzer, fragmenter, formatter, top=1)


@hookimpl
def devpiweb_indexer_backend():
    return dict(
        indexer=Index,
        name="whoosh",
        description="Whoosh indexer backend")


@devpiserver_hookimpl(optionalhook=True)
def devpiserver_metrics(request):
    indexer = request.registry.get('search_index')
    shared_data = getattr(indexer, 'shared_data', None)
    result = []
    if isinstance(shared_data, IndexingSharedData):
        result.extend([
            ('devpi_web_whoosh_index_queue_size', 'gauge', shared_data.queue.qsize()),
            ('devpi_web_whoosh_index_error_queue_size', 'gauge', shared_data.error_queue.qsize())])
    return result


@hookimpl
def devpiweb_get_status_info(request):
    indexer = request.registry.get('search_index')
    shared_data = getattr(indexer, 'shared_data', None)
    msgs = []
    if isinstance(shared_data, IndexingSharedData):
        now = time.time()
        qsize = shared_data.queue.qsize()
        if qsize:
            last_activity_seconds = 0
            if shared_data.last_processed is None and shared_data.last_added:
                last_activity_seconds = (now - shared_data.last_added)
            elif shared_data.last_processed:
                last_activity_seconds = (now - shared_data.last_processed)
            if last_activity_seconds > 300:
                msgs.append(dict(status="fatal", msg="Nothing indexed for more than 5 minutes"))
            elif last_activity_seconds > 60:
                msgs.append(dict(status="warn", msg="Nothing indexed for more than 1 minute"))
            if qsize > 10:
                msgs.append(dict(status="warn", msg="%s items in index queue" % qsize))
        error_qsize = shared_data.error_queue.qsize()
        if error_qsize:
            msgs.append(dict(status="warn", msg="Errors during indexing"))
    return msgs
