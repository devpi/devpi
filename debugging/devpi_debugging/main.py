from pluggy import HookimplMarker


hookimpl = HookimplMarker("devpiserver")


@hookimpl
def devpiserver_add_parser_options(parser):
    debugging = parser.addgroup("debugging options")
    debugging.addoption(
        "--debug-keyfs", action="store_true",
        help="enable the +keyfs views")


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
