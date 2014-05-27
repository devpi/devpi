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


def test_search_after_register(mapp, testapp):
    api = mapp.create_and_use()
    mapp.register_metadata({
        "name": "pkg1",
        "version": "2.6",
        "description": "foo"})
    r = testapp.get('/+search?query=foo')
    assert r.status_code == 200
    links = r.html.select('.searchresults a')
    assert [(l.text.strip(), l.attrs['href']) for l in links] == [
        ("pkg1", "http://localhost:80/%s/pkg1/2.6" % api.stagename)]
    mapp.register_metadata({
        "name": "pkg1",
        "version": "2.7",
        "description": "foo"})
    r = testapp.get('/+search?query=foo')
    assert r.status_code == 200
    links = r.html.select('.searchresults a')
    assert [(l.text.strip(), l.attrs['href']) for l in links] == [
        ("pkg1", "http://localhost:80/%s/pkg1/2.7" % api.stagename)]
    r = testapp.get('/+search?query=foo')
    assert r.status_code == 200
    links = r.html.select('.searchresults a')
    assert [(l.text.strip(), l.attrs['href']) for l in links] == [
        ("pkg1", "http://localhost:80/%s/pkg1/2.7" % api.stagename)]
