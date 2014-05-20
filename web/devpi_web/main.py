from __future__ import unicode_literals
from devpi_web.doczip import devpiserver_docs_uploaded


(devpiserver_docs_uploaded,)  # shutup pyflakes


def includeme(config):
    config.include('pyramid_chameleon')
    config.add_route('root', '/', accept='text/html')
    config.add_route(
        "docroot",
        "/{user}/{index}/{name}/{version}/+doc/{relpath:.*}")
    config.scan()


def devpiserver_pyramid_configure(config, pyramid_config):
    # by using include, the package name doesn't need to be set explicitly
    # for registrations of static views etc
    pyramid_config.include('devpi_web.main')
