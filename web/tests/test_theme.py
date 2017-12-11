import pytest


@pytest.fixture
def themedir(tmpdir):
    path = tmpdir.join('theme')
    path.ensure_dir()
    path.join('static').ensure_dir()
    path.join('templates').ensure_dir()
    return path


@pytest.fixture
def xom(request, xom, themedir):
    xom.config.args.theme = themedir.strpath
    return xom


def test_macro_overwrite(testapp, themedir):
    from devpi_web import __version__
    themedir.join('templates', 'macros.pt').write("""
<metal:head define-macro="headcss" use-macro="request.macros['original-headcss']">
    <metal:mycss fill-slot="headcss">
        <link rel="stylesheet" type="text/css" href="${request.theme_static_url('style.css')}" />
    </metal:mycss>
</metal:head>
    """)
    r = testapp.get('/')
    styles = [x.attrs.get('href') for x in r.html.findAll('link')]
    assert 'http://localhost/+static-%s/style.css' % __version__ in styles
    assert 'http://localhost/+theme-static-%s/style.css' % __version__ in styles


def test_template_overwrite(testapp, themedir):
    themedir.join('templates', 'root.pt').write("Foo Template!")
    r = testapp.get('/')
    assert r.text == 'Foo Template!'


def test_theme_style(testapp, themedir):
    from devpi_web import __version__
    themedir.join('static', 'style.css').write("Foo Style!")
    r = testapp.get('/+theme-static-%s/style.css' % __version__)
    assert r.text == 'Foo Style!'
