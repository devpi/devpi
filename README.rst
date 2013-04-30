devpi-server: on-demand deep pypi.python.org cache
===========================================================

devpi-server puts an end to unreliable installs of pypi-indexed
packages.  It acts as a caching proxy frontend for pypi.python.org
and provides features not found in any other PyPI proxy server:

- caches pypi.python.org index and release file information on demand,
  including indexes and files from 3rd party sites.  

- allows pip/easy_install/buildout to avoid all client-side crawling,
  thus providing lightning-fast and reliable installation.

- automatically updates its cache using pypi's changelog protocol

devpi-server is designed to satisfy all needs arising from 
pip/easy_install installation operations and can thus act
as the sole entry point for all package installation interactions.

Getting started 
----------------------------

Simply install ``devpi-server`` via for example::

    pip install devpi-server # or
    easy_install devpi-server

Make sure you have the ``redis-server`` binary available and issue::

    devpi-server

after which a http server is running on ``localhost:3141`` and you
can use the following index url with pip or easy_install::

    pip install -i http://localhost:3141/ext/pypi/simple/ ...
    easy_install -i http://localhost:3141/ext/pypi/simple/ ...

To avoid having to re-type the URL, you can configure pip by either
setting the environment variable ``PIP_INDEX_URL`` to 
``http://localhost:3141/ext/pypi/simple/`` or by putting an 
according entry in your ``$HOME/.pip/pip.conf`` (posix) or 
``$HOME/pip/pip.conf``::

    [global]
    index-url == http://localhost:3141/ext/pypi/simple/


Compatibility
--------------------

``devpi-server`` works with python2.6 and python2.7 on both
Linux and Windows environments.  Windows support is somewhat
experiment -- better don't run a company wide server with it.  
OSX is untested as of now but no issues are expected -- please 
report if it works for you.

``devpi-server`` requires ``redis-server`` with versions
2.4 or later.  Earlier versions may or may not work (untested).


Deployment notes
----------------------------

By default, devpi-server configures and starts its own redis instance. 
For this it needs to find a ``redis-server`` executable.  On windows it 
will, in addition to the PATH variable, also check for 
``c:\\program files\redis\redis-server.exe`` which is the default
install location for the `windows redis fork installer <https://github.com/rgl/redis/downloads>`. 

In a production setting you might want to use the ``--redismode=manual``
and ``--redisport NUM`` options to rather control the setup of redis 
yourself.  You might also want to use the ``--datadir`` option to
specify where release files will be cached.

Lastly, if you run ``devpi-server`` in a company network, you can for example
proxy-serve the application through an nginx site configuration like this::

    # sample nginx conf
    server {
        server_name your.server.name;
        listen 80;
        root /home/devpi/.devpi/httpfiles/;  # arbitrary for now
        location / {
            proxy_pass http://localhost:3141;
            proxy_set_header  X-Real-IP $remote_addr;
        }
    }


command line options 
---------------------

A list of all devpi-server options::

    $ devpi-server -h
    Usage: devpi-server [options]
    
    Options:
      -h, --help            show this help message and exit
    
      main options:
        --version           show devpi_version (0.7)
        --datadir=DIR       data directory for devpi-server [~/.devpi/serverdata]
        --port=PORT         port to listen for http requests [3141]
        --redisport=PORT    redis server port number [3142]
        --redismode=auto|manual
                            whether to start redis as a sub process [auto]
        --bottleserver=TYPE
                            bottle server class, you may try eventlet or others
                            [wsgiref]
        --debug             run wsgi application with debug logging
    
      pypi upstream options:
        --pypiurl=url       base url of remote pypi server
                            [https://pypi.python.org/]
        --refresh=SECS      periodically pull changes from pypi.python.org [60]

Project status and next steps
-----------------------------

``devpi-server`` is considered beta because it's just an initial release.

It is is tested through tox and has all of its automated pytest suite 
passing for python2.7 and python2.6 on Ubuntu 12.04 and Windows 7.

``devpi-server`` is actively developed and will see more releases in 2013,
in particular for supporting private indexes. You are very welcome
to join, discuss and contribute:

* mailing list: https://groups.google.com/d/forum/devpi-dev

* repository: http://bitbucket.org/hpk42/devpi-server

* Bugtracker: http://bitbucket.org/hpk42/devpi-server/issues
