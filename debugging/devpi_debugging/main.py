from devpi_server.config import hookimpl


@hookimpl
def devpiserver_pyramid_configure(config, pyramid_config):
    pyramid_config.include('devpi_debugging.main')


def includeme(config):
    config.add_route(
        "keyfs",
        "/+keyfs")
    config.add_route(
        "keyfs_changelog",
        "/+keyfs/{serial}")
    config.scan()
