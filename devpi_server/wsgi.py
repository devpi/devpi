"""

devpi_server wsgi application creation.
In order to work nicely with different wsgi servers:

- don't instantiate resources/database connections during
  creation of the wsgi app

"""
from devpi_server.types import lazydecorator
from bottle import Bottle, response

import os
from logging import getLogger
log = getLogger(__name__)

from py.xml import html

def simple_html_body(title, bodytags):
    return html.html(
        html.head(
            html.title(title)
        ),
        html.body(
            html.h1(title),
            *bodytags
        )
    )

route = lazydecorator()

class PyPIView:
    def __init__(self, extdb):
        self.extdb = extdb

    @route("/ext/pypi/<projectname>")
    @route("/ext/pypi/<projectname>/")
    def extpypi_simple(self, projectname):
        result = self.extdb.getreleaselinks(projectname)
        if isinstance(result, int):
            raise BadGateway()
        links = []
        for entry in result:
            href = "/pkg/" + entry.relpath
            if entry.eggfragment:
                href += "#egg=%s" % entry.eggfragment
            elif entry.md5:
                href += "#md5=%s" % entry.md5
            links.append((href, entry.basename))

        # construct html
        body = []
        for entry in links:
            body.append(html.a(entry[1], href=entry[0]))
            body.append(html.br())
        return simple_html_body("links for %s" % projectname, body).unicode()

class PkgView:
    def __init__(self, filestore, httpget):
        self.filestore = filestore
        self.httpget = httpget

    @route("/pkg/<relpath:re:.*>")
    def pkgserv(self, relpath):
        headers, itercontent = self.filestore.iterfile(relpath, self.httpget)
        response.content_type = headers["content-type"]
        response.content_length = headers["content-length"]
        for x in itercontent:
            yield x

def configure_xom(argv=None):
    from devpi_server.main import preparexom
    if argv is None:
        argv = ["devpi_server"]
    log.info("setting up resources %s", os.getpid())
    xom = preparexom(["devpi_server"])
    xom.extdb = xom.hook.resource_extdb(xom=xom)
    xom.releasefilestore = xom.extdb.releasefilestore
    xom.httpget = xom.extdb.htmlcache.httpget
    return xom

def create_app():
    import os
    log.info("creating application %s", os.getpid())
    xom = configure_xom()
    #start_background_tasks_if_not_in_arbiter(xom)
    app = Bottle()
    pypiview = PyPIView(xom.extdb)
    route.discover_and_call(pypiview, app.route)
    pkgview = PkgView(xom.releasefilestore, xom.httpget)
    route.discover_and_call(pkgview, app.route)
    return app

# this flag indicates if we are running in the gunicorn master server
# if so, we don't start background tasks
workers = []

def post_fork(server, worker):
    # this hook is called by gunicorn in a freshly forked worker process
    workers.append(worker)
    log.debug("post_fork %s %s pid %s", server, worker, os.getpid())
    #log.info("vars %r", vars(worker))

def start_background_tasks_if_not_in_arbiter(xom):
    log.info("checking if running in worker %s", os.getpid())
    if not workers:
        return
    log.info("starting background tasks in pid %s", os.getpid())
    from devpi_server.extpypi import RefreshManager, XMLProxy
    xom.proxy = XMLProxy("http://pypi.python.org/pypi/")
    refresher = RefreshManager(xom.extdb, xom)
    xom.spawn(refresher.spawned_pypichanges,
              args=(xom.proxy, lambda: xom.sleep(5)))
    log.info("returning from background task starting")
    xom.spawn(refresher.spawned_refreshprojects,
              args=(lambda: xom.sleep(5),))

default_logging_config = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'standard': {
            'format': '%(asctime)s [%(levelname)-5.5s] %(name)s: %(message)s'
        },
    },
    'handlers': {
        'default': {
            'level':'DEBUG',
            'class':'logging.StreamHandler',
            'formatter': 'standard',
        },
    },
    'loggers': {
        '': {
            'handlers': ['default'],
            'level': 'DEBUG',
            'propagate': False,
        },
        'devpi_server': {
            'handlers': ['default'],
            'level': 'DEBUG',
            'propagate': False,
        },
    }
}

if __name__ == "__main__":
    import logging.config
    logging.config.dictConfig(default_logging_config, )
    from bottle import run
    run(app="devpi_server.wsgi:create_app()", server="eventlet",
        reloader=True, debug=True, port=3141)

#else:
#    def app(environ, start_response, started=[]):
#        if not started:
#            started.append(create_app())
#        return started[0](environ, start_response)
