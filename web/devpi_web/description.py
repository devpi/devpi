from __future__ import unicode_literals
from devpi_common.validation import normalize_name
from devpi_web.vendor._description_utils import processDescription
from devpi_server.log import threadlog
import py


def get_description_file(stage, name, version):
    config = stage.xom.config
    name = normalize_name(name)
    return config.serverdir.join(
        '.web', stage.user.name, stage.index, name, version, 'description.html')


def get_description(stage, name, version):
    is_mirror = (stage.ixconfig['type'] == 'mirror')
    mirror_url = stage.ixconfig.get('mirror_url', '')
    if is_mirror and (stage.name == 'root/pypi' or 'pypi.python.org' in mirror_url):
        html = py.xml.html
        link = "https://pypi.python.org/pypi/%s/%s/" % (name, version)
        return html.div(
            "please refer to description on remote server ",
            html.a(link, href=link)).unicode(indent=2)
    desc_file = get_description_file(stage, name, version)
    if not desc_file.exists():
        verdata = stage.get_versiondata(name, version)
        return '<p class="infonote">The description hasn\'t been rendered yet.</p>\n<pre>%s</pre>' % verdata.get('description', '')
    return py.builtin._totext(desc_file.read(mode='rb'), "utf-8")


def render_description(stage, metadata):
    desc = metadata.get("description")
    name = metadata.get("name")
    version = metadata.get("version")
    if stage is None or desc is None or name is None or version is None:
        return
    html = processDescription(desc)
    if py.builtin._istext(html):
        html = html.encode("utf8")
    desc_file = get_description_file(stage, name, version)
    desc_file.dirpath().ensure_dir()
    desc_file.write(html, mode='wb')
    threadlog.debug("wrote description file: %s", desc_file)
