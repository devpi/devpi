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
            <metal:versions define-macro="versions">
                MyVersions
            </metal:versions>
        """,
        ("templates", "root.pt"): """
            <!DOCTYPE html>
            <html lang="en">
            <head><title>Root</title></head>
            <body>
              <metal:head use-macro="request.macros['versions']" />
            </body>
            </html>
        """,
    }
)
def test_legacy_macro_overwrite(testapp):
    with pytest.warns(
        DeprecationWarning,
        match="The macro 'versions' has been moved to separate 'footer_versions.pt' template.",
    ):
        r = testapp.get("/")
    assert "MyVersions" in r.text


@pytest.mark.usefixtures("theme_path")
@pytest.mark.theme_files(
    {
        ("templates", "macros.pt"): """
            <metal:versions define-macro="versions">
                MyVersions
            </metal:versions>
        """,
        ("templates", "root.pt"): """
            <!DOCTYPE html>
            <html lang="en">
            <head><title>Root</title></head>
            <body>
              <metal:head use-macro="macros.versions" />
            </body>
            </html>
        """,
    }
)
def test_legacy_macro_overwrite_attribute(testapp):
    with pytest.warns(
        DeprecationWarning,
        match="The macro 'versions' has been moved to separate 'footer_versions.pt' template.",
    ):
        r = testapp.get("/")
    assert "MyVersions" in r.text


@pytest.mark.usefixtures("theme_path")
@pytest.mark.theme_files(
    {
        ("templates", "footer_versions.pt"): "MyVersions",
        ("templates", "root.pt"): """
            <!DOCTYPE html>
            <html lang="en">
            <head><title>Root</title></head>
            <body>
              <metal:head use-macro="macros.footer_versions" />
            </body>
            </html>
        """,
    }
)
def test_macro_overwrite(testapp):
    r = testapp.get("/")
    assert "MyVersions" in r.text


@pytest.mark.usefixtures("theme_path")
@pytest.mark.theme_files(
    {
        ("templates", "html_head_css.pt"): """
            <metal:head use-macro="macros.original_html_head_css">
                <metal:mycss fill-slot="headcss">
                    <style></style>
                </metal:mycss>
            </metal:head>
        """
    }
)
def test_macro_overwrite_reuse(testapp):
    r = testapp.get('/')
    assert "<style></style>" in r.text
    assert "/style.css" in r.text


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


@pytest.mark.theme_files({("static", "style.css"): "Foo Style!"})
def test_theme_style(dummyrequest, pyramidconfig, testapp, theme_path):
    from devpi_web import __version__
    from devpi_web.macros import html_head_css
    from devpi_web.main import add_href_css
    from devpi_web.main import add_static_css
    from devpi_web.main import theme_static_url

    r = testapp.get(f"/+theme-static-{__version__}/style.css")
    assert r.text == 'Foo Style!'
    pyramidconfig.add_static_view("+static", "devpi_web:static")
    pyramidconfig.add_static_view("+theme-static", str(theme_path))
    dummyrequest.registry["theme_path"] = str(theme_path)
    dummyrequest.add_href_css = add_href_css.__get__(dummyrequest)
    dummyrequest.add_static_css = add_static_css.__get__(dummyrequest)
    dummyrequest.theme_static_url = theme_static_url.__get__(dummyrequest)
    assert html_head_css(dummyrequest) == dict(
        css=[
            dict(
                href="http://example.com/%2Bstatic/style.css",
                rel="stylesheet",
                type="text/css",
            ),
            dict(
                href="http://example.com/%2Btheme-static/static/style.css",
                rel="stylesheet",
                type="text/css",
            ),
        ]
    )


@pytest.mark.theme_files(
    {
        ("theme.toml",): """
            [macros.mymacro]
            template = "mymacro.pt"
        """,
        ("templates", "mymacro.pt"): """
            MyMacro
        """,
        ("templates", "root.pt"): """
            <!DOCTYPE html>
            <html lang="en">
            <head><title>Root</title></head>
            <body>
              <metal:macro use-macro="request.macros.mymacro" />
            </body>
            </html>
        """,
    }
)
def test_theme_toml_macro(testapp):
    r = testapp.get("/")
    assert "MyMacro" in r.text
