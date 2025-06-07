import pytest


pytestmark = [pytest.mark.notransaction]


@pytest.fixture
def xom(xom, theme_path):
    xom.config.args.theme = str(theme_path)
    return xom


@pytest.mark.usefixtures("theme_path")
@pytest.mark.theme_files(
    {
        ("templates", "macros.pt"): """
<metal:head define-macro="headcss" use-macro="request.macros['original-headcss']">
    <metal:mycss fill-slot="headcss">
        <link rel="stylesheet" type="text/css" href="${request.theme_static_url('style.css')}" />
    </metal:mycss>
</metal:head>
    """
    }
)
def test_macro_overwrite_reuse(testapp):
    from devpi_web import __version__

    r = testapp.get('/')
    styles = [x.attrs.get('href') for x in r.html.find_all('link')]
    assert 'http://localhost/+static-%s/style.css' % __version__ in styles
    assert 'http://localhost/+theme-static-%s/style.css' % __version__ in styles


@pytest.mark.usefixtures("theme_path")
@pytest.mark.theme_files(
    {
        ("templates", "macros.pt"): """
            <metal:mymacro define-macro="mymacro">
                MyMacro
            </metal:mymacro>
        """,
        ("templates", "root.pt"): """
            <!DOCTYPE html>
            <html lang="en">
            <head><title>Root</title></head>
            <body>
              <metal:macro use-macro="request.macros['mymacro']" />
            </body>
            </html>
        """,
    }
)
def test_new_macro(testapp):
    r = testapp.get("/")
    assert "MyMacro" in r.text


@pytest.mark.usefixtures("theme_path")
@pytest.mark.theme_files(
    {
        ("templates", "root.pt"): """
            <!DOCTYPE html>
            <html lang="en">
            <head><title>Root</title></head>
            <body>
                Foo Template!
            </body>
            </html>
        """
    }
)
def test_template_overwrite(testapp):
    r = testapp.get('/')
    assert "Foo Template!" in r.text


@pytest.mark.usefixtures("theme_path")
@pytest.mark.theme_files({("static", "style.css"): "Foo Style!"})
def test_theme_style(testapp):
    from devpi_web import __version__

    r = testapp.get(f"/+theme-static-{__version__}/style.css")
    assert r.text == 'Foo Style!'
