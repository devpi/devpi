from __future__ import unicode_literals
from collections import defaultdict
from devpi_common.types import cached_property
from logging import getLogger
from whoosh import fields
from whoosh.analysis import Token, Tokenizer
from whoosh.compat import text_type, u
from whoosh.index import create_in, exists_in, open_dir
from whoosh.index import IndexError as WhooshIndexError
from whoosh.qparser import QueryParser
from whoosh.util.text import rcompile
from whoosh.writing import CLEAR
import threading


log = getLogger(__name__)


class ProjectNameTokenizer(Tokenizer):
    def __init__(self):
        self.expression = rcompile('(\W|_)')

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
    return ' '.join(x[2] for x in tokenizer.iter_value(name))


class SearchUnavailableException(Exception):
    pass


class Index(object):
    SearchUnavailableException = SearchUnavailableException

    def __init__(self, index_path):
        self.index_path = index_path
        self.tl = threading.local()

    def ix(self, name):
        if not exists_in(self.index_path, indexname=name):
            schema = getattr(self, '%s_schema' % name)
            return create_in(self.index_path, schema, indexname=name)
        return open_dir(self.index_path, indexname=name)

    def needs_reindex(self):
        if self.project_ix.is_empty():
            return True
        return self.project_ix.schema != self.project_schema

    @cached_property
    def project_ix(self):
        return self.ix('project')

    @property
    def project_schema(self):
        return fields.Schema(
            path=fields.ID(stored=True, unique=True),
            name=fields.ID(stored=True),
            user=fields.ID(stored=True),
            index=fields.ID(stored=True),
            classifiers=fields.KEYWORD(commas=True, scorable=True),
            keywords=fields.KEYWORD(stored=True, commas=True, scorable=True),
            version=fields.STORED(),
            doc_version=fields.STORED(),
            text_type=fields.ID(stored=True),
            text_path=fields.STORED(),
            text_title=fields.STORED(),
            text=fields.TEXT(stored=False))

    def update_projects(self, projects, clear=False):
        writer = self.project_ix.writer()
        main_keys = self.project_ix.schema.names()
        text_keys = (
            ('author', 0.5),
            ('author_email', 0.5),
            ('description', 1.5),
            ('summary', 1.75),
            ('keywords', 1.75))
        for project in projects:
            data = dict((u(x), project[x]) for x in main_keys if x in project)
            data['path'] = u"/{user}/{index}/{name}".format(**data)
            if not clear:
                writer.delete_by_term('path', data['path'])
            data['text_type'] = "project"
            data['text'] = project_name(data['name'])
            data['_text_boost'] = 0.5
            with writer.group():
                writer.add_document(**data)
                for key, boost in text_keys:
                    if key not in project:
                        continue
                    writer.add_document(**{
                        "path": data['path'],
                        "text_type": key,
                        "text": project[key],
                        "_text_boost": boost})
                if '+doczip' not in project:
                    continue
                for page in project['+doczip']:
                    writer.add_document(**{
                        "path": data['path'],
                        "text_type": "title",
                        "text": page['title'],
                        "text_path": page['path'],
                        "text_title": page['title'],
                        "_text_boost": 1.5})
                    writer.add_document(**{
                        "path": data['path'],
                        "text_type": "page",
                        "text": page['text'],
                        "text_path": page['path'],
                        "text_title": page['title'],
                        "_text_boost": 1.0})
        log.info("Committing index.")
        if clear:
            writer.commit(mergetype=CLEAR)
        else:
            writer.commit()

    @property
    def project_searcher(self):
        try:
            searcher = self.tl.searcher
        except AttributeError:
            searcher = self.project_ix.searcher()
        searcher = searcher.refresh()
        self.tl.searcher = searcher
        return searcher

    def _process_results(self, raw, page=1):
        items = []
        result_info = dict()
        result = {"items": items, "info": result_info}
        found = raw.scored_length()
        result_info['found'] = found
        result_info['total'] = raw.total
        result_info['pagecount'] = raw.pagecount
        result_info['pagenum'] = raw.pagenum
        collapsed_counts = defaultdict(int)
        result_info['collapsed_counts'] = collapsed_counts
        fields = set(x.field() for x in raw.results.q.leaves())
        collapse = "path" not in fields
        parents = {}
        for item in raw:
            info = {"data": dict(item)}
            for attr in ('docnum', 'pos', 'rank', 'score'):
                info[attr] = getattr(item, attr)
            path = item['path']
            if path in parents:
                parent = parents[path]
            elif info['data'].get('text_type') == 'project':
                parent = parents[path] = dict(info)
                parent['sub_hits'] = []
                items.append(parent)
            else:
                parent = {
                    "data": item.searcher.document(path=path),
                    "sub_hits": []}
                parents[path] = parent
                items.append(parent)
            if collapse and len(parent['sub_hits']) > 2:
                collapsed_counts[path] = collapsed_counts[path] + 1
            else:
                parent['sub_hits'].append(info)
        return result

    def _search_projects(self, query, page=1):
        searcher = self.project_searcher
        return searcher.search_page(query, page)

    def _query_parser_plugins(self):
        from whoosh.qparser import plugins
        return [
            plugins.WhitespacePlugin(),
            plugins.SingleQuotePlugin(),
            plugins.FieldsPlugin(),
            plugins.PrefixPlugin(),
            plugins.PhrasePlugin(),
            plugins.GroupPlugin(),
            plugins.OperatorsPlugin(),
            plugins.BoostPlugin(),
            plugins.EveryPlugin()]

    def _query_projects(self, querystring, page=1):
        parser = QueryParser(
            "text", self.project_ix.schema,
            plugins=self._query_parser_plugins())
        query = parser.parse(querystring)
        return self._search_projects(query, page=page)

    def search_projects(self, query, page=1):
        try:
            return self._process_results(
                self._search_projects(query, page=page))
        except (OSError, WhooshIndexError) as e:
            raise SearchUnavailableException(e)

    def query_projects(self, querystring, page=1):
        try:
            return self._process_results(
                self._query_projects(querystring, page=page))
        except (OSError, WhooshIndexError) as e:
            raise SearchUnavailableException(e)
