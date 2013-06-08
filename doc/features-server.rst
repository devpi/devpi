
devpi-server features
=====================================

.. include:: links.rst


consistent robust pypi-cache
----------------------------------------

You can point ``pip or easy_install`` to the ``root/pypi/+simple/``
index, serving as a self-updating transparent cache for pypi-hosted
**and** external packages.  Cache-invalidation uses the latest and
greatest PyPI protocols.  The cache index continues to serve when
offline and will resume cache-updates once network is available.

github-style indexes
---------------------------------

Each user can have multiple indexes and upload packages and docs via
standard ``setup.py`` invocations.  Users, indexes (and soon projects
and releases) are manipulaed through a RESTful HTTP API.

index inheritance
--------------------------

Each index can be configured to merge in other indexes so that it serves
both its uploads and all releases from other index(es).  For example, an
index using ``root/pypi`` as a parent is a good place to test out a
release candidate before you push it to PyPI.

good defaults and easy deployment
---------------------------------------

Get started easily and create a permanent devpi-server deployment
including pre-configured templates for nginx_ and cron. 

separate tool for Packaging/Testing activities
-------------------------------------------------------

The complimentary `command line tool devpi <devpi>`_ helps to manage
users, indexes, logins and typical setup.py-based upload and
installation workflows.

command line options 
---------------------

A list of all devpi-server options::

    $ devpi-server -h
    usage: devpi-server [-h] [--version] [--datadir DIR] [--port PORT]
                        [--host HOST] [--refresh SECS] [--gendeploy DIR]
                        [--secretfile path] [--bottleserver TYPE] [--debug]
    
    Start an index server acting as a cache for pypi.python.org, suitable for
    pip/easy_install usage. The server automatically refreshes the cache of all
    indexes which have changed on the pypi.python.org side.
    
    optional arguments:
      -h, --help           show this help message and exit
    
    main:
      main options
    
      --version            show devpi_version (0.9.dev8)
      --datadir DIR        directory for server data [~/.devpi/server]
      --port PORT          port to listen for http requests [3141]
      --host HOST          domain/ip address to listen on [localhost]
      --refresh SECS       interval for consulting changelog api of
                           pypi.python.org [60]
    
    deploy:
      deployment options
    
      --gendeploy DIR      (unix only) generate a pre-configured self-contained
                           virtualenv directory which puts devpi-server under
                           supervisor control. Also provides nginx/cron files to
                           help with permanent deployment.
      --secretfile path    file containing the server side secret used for user
                           validation. If it does not exist, a random secret is
                           generated on start up and used subsequently.
                           [~/.devpi/server/.secret]
      --bottleserver TYPE  bottle server class, you may try eventlet or others
                           [wsgiref]
      --debug              run wsgi application with debug logging

