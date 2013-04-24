from pyramid.config import Configurator


def main(global_config, **settings):
    """ This function returns a Pyramid WSGI application.
    """
    from devpi_server.main import preparexom
    xom = preparexom(["devpi_server"])
    xom.extdb = xom.hook.resource_extdb(xom=xom)
    xom.releasefilestore = xom.extdb.releasefilestore
    xom.httpget = xom.extdb.htmlcache.httpget
    def xom_factory(request):
        return xom

    config = Configurator(settings=settings)
    config.add_static_view('static', 'static', cache_max_age=3600)
    config.add_route('home', '/')
    config.add_route('extpypi_simple', '/extpypi/simple/{projectname}/',
                     factory=xom_factory)
    config.add_route('pkgserve', '/pkg/*relpath',
                     factory=xom_factory)
    config.scan()
    return config.make_wsgi_app()


