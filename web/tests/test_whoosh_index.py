from __future__ import unicode_literals
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
    api = mapp.create_and_use()
    mapp.set_versiondata({
        "name": "pkg1",
        "version": "2.6",
        "description": "foo"}, waithooks=True)
    r = testapp.get('/+search?query=foo', expect_errors=False)
    links = r.html.select('.searchresults a')
    assert [(l.text.strip(), l.attrs['href']) for l in links] == [
        ("pkg1-2.6", "http://localhost/%s/pkg1/2.6" % api.stagename),
        ("Description", "http://localhost/%s/pkg1/2.6#description" % api.stagename)]
    mapp.set_versiondata({
        "name": "pkg1",
        "version": "2.7",
        "description": "foo"}, waithooks=True)
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
