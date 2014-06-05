from __future__ import unicode_literals
from collections import defaultdict
from devpi_common.types import cached_property
from logging import getLogger
from whoosh import fields
from whoosh.analysis import Filter, LowercaseFilter, RegexTokenizer
from whoosh.analysis import Token, Tokenizer
from whoosh.compat import text_type, u
from whoosh.highlight import ContextFragmenter, HtmlFormatter, highlight
from whoosh.index import create_in, exists_in, open_dir
from whoosh.index import IndexError as WhooshIndexError
from whoosh.qparser import QueryParser
from whoosh.util.text import rcompile
from whoosh.writing import CLEAR
import shutil
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

    def delete_index(self):
        shutil.rmtree(self.index_path)

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
            text=fields.TEXT(analyzer=NgramWordAnalyzer(), stored=False, phrase=False))

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
            data['text'] = "%s %s" % (data['name'], project_name(data['name']))
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
        text_field = raw.results.searcher.schema['text']
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
            if collapse and len(parent['sub_hits']) > 3:
                collapsed_counts[path] = collapsed_counts[path] + 1
            else:
                parent['sub_hits'].append(info)
        return result

    def _search_projects(self, query, page=1):
        searcher = self.project_searcher
        return searcher.search_page(query, page, terms=True)

    def _query_parser_plugins(self):
        from whoosh.qparser import plugins
        return [
            plugins.WhitespacePlugin(),
            plugins.SingleQuotePlugin(),
            plugins.FieldsPlugin(),
            plugins.PrefixPlugin(),
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

    def highlight(self, text, words):
        fragmenter = ContextFragmenter()
        formatter = HtmlFormatter()
        analyzer = self.project_schema['text'].analyzer
        return highlight(text, words, analyzer, fragmenter, formatter, top=1)
