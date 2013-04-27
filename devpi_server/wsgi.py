from pyramid.config import Configurator

import os
from logging import getLogger
log = getLogger(__name__)

def configure_xom(argv=None):
    from devpi_server.main import preparexom
    if argv is None:
        argv = ["devpi_server"]
    xom = preparexom(["devpi_server"])
    xom.extdb = xom.hook.resource_extdb(xom=xom)
    xom.releasefilestore = xom.extdb.releasefilestore
    xom.httpget = xom.extdb.htmlcache.httpget
    return xom

def main(**settings):
    """ This function returns a Pyramid WSGI application.
    """
    log.info("creating application")
    xom = configure_xom()
    def xom_factory(request):
        return xom
    start_background_tasks_if_not_in_arbiter(xom)
    config = Configurator(settings=settings)
    config.add_static_view('static', 'static', cache_max_age=3600)
    config.add_route('home', '/')
    config.add_route('extpypi_simple', '/extpypi/simple/{projectname}/',
                     factory=xom_factory)
    config.add_route('pkgserve', '/pkg/*relpath',
                     factory=xom_factory)
    config.scan()
    return config.make_wsgi_app()


# this flag indicates if we are running in the gunicorn master server
# if so, we don't start background tasks
workers = []

def post_fork(server, worker):
    # this hook is called by gunicorn in a freshly forked worker process
    import logging
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

application = main()
