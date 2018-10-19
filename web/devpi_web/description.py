from __future__ import unicode_literals
import io
import py
import readme_renderer.markdown
import readme_renderer.rst
import readme_renderer.txt


def get_description(stage, name, version):
    return DescriptionRenderer(
        stage, name, version).get_description()


class DescriptionRenderer:

    DEFAULT_DESCRIPTION = '<p>No description in metadata</p>'

    def __init__(self, stage, name, version):
        """ Initialiser.

        :return: void
        """
        self.name = name
        self.stage = stage
        self.version = version
        self.metadata = self.stage.get_versiondata(
            self.name, self.version)

    def get_description(self):
        """ Fetch the desciption.

        :return: string
        """
        if self._is_mirror():
            return self._render_mirror_description()
        desc = self.metadata.get('description')
        if not desc:
            return self._force_text(self.DEFAULT_DESCRIPTION)

        return self._force_text(
            self._render_description(desc))

    def has_markdown_description(self):
        """ Does this project specify a markdown content-type?

        :return: boolean
        """
        return self.metadata.get(
            'description_content_type', '').lower() == 'text/markdown'

    @staticmethod
    def _force_text(html):
        """ Ensure we return unicode html.

        :return: string
        """
        if py.builtin._istext(html):
            return html
        return py.builtin._totext(html, 'utf-8')

    def _render_mirror_description(self):
        """ Generate a description with a link to the remote mirror's description.

        :return: string
        """
        link = self._get_mirror_web_url_fmt().format(
            name=self.name).rstrip('/') + '/%s/' % self.version

        html = py.xml.html
        return html.div(
            'Please refer to description on remote server ',
            html.a(link, href=link)).unicode(indent=2)

    def _render_description(self, desc):
        """ Render a markdown or RST description.

        :return: string
        """
        warnings = io.StringIO()

        if self.has_markdown_description():
            html = readme_renderer.markdown.render(desc, stream=warnings)
        else:
            html = readme_renderer.rst.render(desc, stream=warnings)

        warnings = warnings.getvalue()
        if warnings:
            desc = '%s\n\nRender warnings:\n%s' % (desc, warnings)

        if html is None:
            html = readme_renderer.txt.render(desc)

        return html

    def _is_mirror(self):
        """ Is this package a mirror of a remote?

        :return: boolean
        """
        return self.stage.ixconfig['type'] == 'mirror' \
            and self._get_mirror_web_url_fmt() is not None

    def _get_mirror_web_url_fmt(self):
        """ Fetch the remote's source url.

        :return: string
        """
        return self.stage.ixconfig.get('mirror_web_url_fmt')
