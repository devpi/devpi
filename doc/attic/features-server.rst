
devpi-server features
=====================================

.. include:: links.rst


command line options 
---------------------

A list of all devpi-server options::

    $ devpi-server -h
    usage: devpi-server [-h] [--version] [serverdir DIR] [--port PORT]
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
      serverdir DIR        directory for server data [~/.devpi/server]
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

