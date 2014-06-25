from __future__ import unicode_literals
from devpi_web.vendor._description_utils import processDescription
import py


def get_description_file(stage, name, version):
    config = stage.xom.config
    return config.serverdir.join(
        '.web', stage.user.name, stage.index, name, version, 'description.html')


def get_description(stage, name, version):
    if stage.name == 'root/pypi':
        html = py.xml.html
        link = "https://pypi.python.org/pypi/%s/%s/" % (name, version)
        return html.div(
            "please refer to description on remote server ",
            html.a(link, href=link)).unicode(indent=2)
    desc_file = get_description_file(stage, name, version)
    if not desc_file.exists():
        metadata = stage.get_projectconfig(name)
        verdata = metadata.get(version)
        return "<p>The description hasn't been rendered yet.</p>\n<pre>%s</pre>" % verdata.get('description', '')
    return py.builtin._totext(desc_file.read(), "utf-8")


def render_description(stage, metadata):
    desc = metadata.get("description")
    name = metadata.get("name")
    version = metadata.get("version")
    if desc is None or name is None or version is None:
        return
    html = processDescription(desc)
    if py.builtin._istext(html):
        html = html.encode("utf8")
    desc_file = get_description_file(stage, name, version)
    desc_file.dirpath().ensure_dir()
    desc_file.write(html)
