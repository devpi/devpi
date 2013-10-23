# copied from bitbucket.org/pypa/pypi repo (for now)
# removed extract_package_readme function

import sys
import cgi

from docutils.core import publish_doctree, Publisher
from docutils.transforms import TransformError
from docutils import io, readers
try:
    from io import StringIO
    import urllib.parse as urlparse
except ImportError:
    # PY2
    from StringIO import StringIO
    import urlparse


# BEGIN PYGMENTS SUPPORT BLOCK
# <RJ> the following is included from pygments' external / rst-directive.py
# because the docutils version on both testpypi and pypi prod does not include
# pygments support (I believe 0.9 is the minimum requirement.) If that's ever
# resolved then this PYGMENTS SUPPORT BLOCK may be removed.

# Set to True if you want inline CSS styles instead of classes
INLINESTYLES = False

from pygments.formatters import HtmlFormatter

# The default formatter
DEFAULT = HtmlFormatter(noclasses=INLINESTYLES)

# Add name -> formatter pairs for every variant you want to use
VARIANTS = {
    # 'linenos': HtmlFormatter(noclasses=INLINESTYLES, linenos=True),
}


from docutils import nodes
from docutils.parsers.rst import directives, Directive

from pygments import highlight
from pygments.lexers import get_lexer_by_name, TextLexer

class Pygments(Directive):
    """ Source code syntax hightlighting.
    """
    required_arguments = 1
    optional_arguments = 0
    final_argument_whitespace = True
    option_spec = dict([(key, directives.flag) for key in VARIANTS])
    has_content = True

    def run(self):
        self.assert_has_content()
        try:
            lexer = get_lexer_by_name(self.arguments[0])
        except ValueError:
            # no lexer found - use the text one instead of an exception
            lexer = TextLexer()
        # take an arbitrary option if more than one is given
        formatter = DEFAULT
        if self.options:
            variant = VARIANTS[list(self.options.keys())[0]]
            if variant:
                formatter = variant
        parsed = highlight('\n'.join(self.content), lexer, formatter)
        return [nodes.raw('', parsed, format='html')]

directives.register_directive('code', Pygments)
directives.register_directive('code-block', Pygments)   # Sphinx
directives.register_directive('sourcecode', Pygments)
# END PYGMENTS SUPPORT BLOCK

def trim_docstring(text):
    """
    Trim indentation and blank lines from docstring text & return it.

    See PEP 257.
    """
    if not text:
        return text
    # Convert tabs to spaces (following the normal Python rules)
    # and split into a list of lines:
    lines = text.expandtabs().splitlines()
    # Determine minimum indentation (first line doesn't count):
    indent = sys.maxsize
    for line in lines[1:]:
        stripped = line.lstrip()
        if stripped:
            indent = min(indent, len(line) - len(stripped))
    # Remove indentation (first line is special):
    trimmed = [lines[0].strip()]
    if indent < 9999:
        for line in lines[1:]:
            trimmed.append(line[indent:].rstrip())
    # Strip off trailing and leading blank lines:
    while trimmed and not trimmed[-1]:
        trimmed.pop()
    while trimmed and not trimmed[0]:
        trimmed.pop(0)
    # Return a single string:
    return '\n'.join(trimmed)

ALLOWED_SCHEMES = '''file ftp gopher hdl http https imap mailto mms news nntp
prospero rsync rtsp rtspu sftp shttp sip sips snews svn svn+ssh telnet
wais irc'''.split()

def processDescription(source, output_encoding='unicode'):
    """Given an source string, returns an HTML fragment as a string.

    The return value is the contents of the <body> tag.

    Parameters:

    - `source`: A multi-line text string; required.
    - `output_encoding`: The desired encoding of the output.  If a Unicode
      string is desired, use the default value of "unicode" .
    """
    # Dedent all lines of `source`.
    source = trim_docstring(source)

    settings_overrides={
        'raw_enabled': 0,  # no raw HTML code
        'file_insertion_enabled': 0,  # no file/URL access
        'halt_level': 2,  # at warnings or errors, raise an exception
        'report_level': 5,  # never report problems with the reST code
        }

    # capture publishing errors, they go to stderr
    old_stderr = sys.stderr
    sys.stderr = s = StringIO()
    parts = None

    try:
        # Convert reStructuredText to HTML using Docutils.
        document = publish_doctree(source=source,
            settings_overrides=settings_overrides)

        for node in document.traverse():
            if node.tagname == '#text':
                continue
            if node.hasattr('refuri'):
                uri = node['refuri']
            elif node.hasattr('uri'):
                uri = node['uri']
            else:
                continue
            o = urlparse.urlparse(uri)
            if o.scheme not in ALLOWED_SCHEMES:
                raise TransformError('link scheme not allowed')

        # now turn the transformed document into HTML
        reader = readers.doctree.Reader(parser_name='null')
        pub = Publisher(reader, source=io.DocTreeInput(document),
            destination_class=io.StringOutput)
        pub.set_writer('html')
        pub.process_programmatic_settings(None, settings_overrides, None)
        pub.set_destination(None, None)
        pub.publish()
        parts = pub.writer.parts

    except:
        pass

    sys.stderr = old_stderr

    # original text if publishing errors occur
    if parts is None or len(s.getvalue()) > 0:
        output = "".join('<PRE>\n' + cgi.escape(source) + '</PRE>')
    else:
        output = parts['body']

    if output_encoding != 'unicode':
        output = output.encode(output_encoding)

    return output

