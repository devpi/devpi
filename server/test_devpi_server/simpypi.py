# this file is shared via symlink with devpi-client,
# so for the time being it must continue to work with Python 2
from __future__ import print_function
try:
    from html import escape
except ImportError:
    from cgi import escape
import hashlib
try:
    import http.server as httpserver
except ImportError:
    import BaseHTTPServer as httpserver
import sys


def getmd5(s):
    return hashlib.md5(s.encode("utf8")).hexdigest()


def getsha256(s):
    return hashlib.sha256(s.encode("utf8")).hexdigest()


def make_simple_pkg_info(name, text="", pkgver=None, hash_type=None,
                         pypiserial=None, requires_python=None, yanked=False):
    class ret:
        hash_spec = ""
    attribs = ""
    if requires_python:
        attribs = ' data-requires-python="%s"' % escape(requires_python)
    if yanked:
        attribs = ' data-yanked=""'
    if pkgver is not None:
        assert not text
        if hash_type and "#" not in pkgver:
            hv = (pkgver + str(pypiserial)).encode("ascii")
            hash_value = getattr(hashlib, hash_type)(hv).hexdigest()
            ret.hash_spec = "%s=%s" % (hash_type, hash_value)
            pkgver += "#" + ret.hash_spec
        text = '<a href="../../{name}/{pkgver}"{attribs}>{pkgver}</a>'.format(
            name=name, pkgver=pkgver, attribs=attribs)
    elif text and "{md5}" in text:
        text = text.format(md5=getmd5(text))
    elif text and "{sha256}" in text:
        text = text.format(sha256=getsha256(text))
    return ret, text


class SimPyPIRequestHandler(httpserver.BaseHTTPRequestHandler):
    def do_GET(self):
        def start_response(status, headers):
            self.send_response(status)
            for key, value in headers.items():
                self.send_header(key, value)
            self.end_headers()

        simpypi = self.server.simpypi
        headers = {
            'X-Simpypi-Method': 'GET'}
        p = self.path.split('/')
        if len(p) == 4 and p[0] == '' and p[1] == 'simple' and p[3] == '':
            # project listing
            project = simpypi.projects.get(p[2])
            if project is not None:
                releases = project['releases']
                simpypi.add_log(
                    "do_GET", self.path, "found",
                    project['title'], "with", list(releases))
                start_response(200, headers)
                self.wfile.write(b'\n'.join(releases))
                return
        elif p == ['', 'simple', ''] or p == ['', 'simple']:
            # root listing
            projects = [
                '<a href="/simple/%s/">%s</a>' % (k, v['title'])
                for k, v in simpypi.projects.items()]
            simpypi.add_log("do_GET", self.path, "found", list(simpypi.projects))
            start_response(200, headers)
            self.wfile.write(b'\n'.join(x.encode('utf-8') for x in projects))
            return
        elif self.path in simpypi.files:
            # file serving
            f = simpypi.files[self.path]
            content = f['content']
            if 'length' in f:
                headers['Content-Length'] = f['length']
                content = content[:f['length']]
            start_response(200, headers)
            simpypi.add_log("do_GET", self.path, "sending")
            if not f['stream']:
                self.wfile.write(content)
                simpypi.add_log("do_GET", self.path, "sent")
                return
            else:
                chunksize = f['chunksize']
                callback = f.get('callback')
                for i in range(len(content) // chunksize):
                    data = content[i * chunksize:(i + 1) * chunksize]
                    if not data:
                        break
                    self.wfile.write(data)
                    if callback:
                        callback(i * chunksize)
                    simpypi.add_log(
                        "do_GET", self.path,
                        "streamed %i bytes" % (i * chunksize))
                return
        simpypi.add_log("do_GET", self.path, "not found")
        start_response(404, headers)


class SimPyPI:
    def __init__(self, address):
        self.baseurl = "http://%s:%s" % address
        self.simpleurl = "%s/simple" % self.baseurl
        self.projects = {}
        self.files = {}
        self.clear_log()

    def clear_log(self):
        self.log = []

    def add_log(self, *args):
        msg = ' '.join(str(x) for x in args)
        print(msg, file=sys.stderr)
        self.log.append(msg)

    def add_project(self, name, title=None):
        if title is None:
            title = name
        self.projects.setdefault(
            name, dict(
                title=title,
                releases=set(),
                pypiserial=None))
        return self.projects[name]

    def remove_project(self, name):
        self.projects.pop(name)

    def add_release(self, name, title=None, text="", pkgver=None, hash_type=None,
                    pypiserial=None, requires_python=None, yanked=False, **kw):
        project = self.add_project(name, title=title)
        ret, text = make_simple_pkg_info(
            name, text=text, pkgver=pkgver, hash_type=hash_type,
            pypiserial=pypiserial, requires_python=requires_python,
            yanked=yanked)
        assert text
        project['releases'].add(text.encode('utf-8'))

    def add_file(self, relpath, content, stream=False, chunksize=1024,
                 length=None, callback=None):
        if length is None:
            length = len(content)
        info = dict(
            content=content,
            stream=stream,
            chunksize=chunksize,
            callback=callback)
        if length is not False:
            info['length'] = length
        self.files[relpath] = info

    def remove_file(self, relpath):
        del self.files[relpath]
