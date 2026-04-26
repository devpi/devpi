from bs4 import BeautifulSoup
import pytest


pytestmark = [pytest.mark.notransaction]


def test_keyfs_view(testapp):
    r = testapp.get("/+keyfs", headers=dict(accept="text/html"))
    html = BeautifulSoup(r.body, "html.parser")
    (link,) = html.select("a")
    assert link.text == "0"
    assert "/+keyfs/0" in link.attrs["href"]


def test_keyfs_changelog_view(testapp):
    r = testapp.get("/+keyfs/0", headers=dict(accept="text/html"))
    assert "<strong>USER root/.config</strong>" in r.text
