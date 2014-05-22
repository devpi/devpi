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
