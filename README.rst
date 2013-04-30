devpi-server: on-demand deep pypi.python.org cache
===========================================================

devpi-server acts as a caching proxy frontend for pypi.python.org
and provides features not found in any other PyPI server:

- caches pypi.python.org index and release file information on demand,
  including indexes and files from 3rd party sites.

- allows pip/easy_install/buildout to avoid all client-side crawling,
  thus providing lightning-fast and reliable installation.

- automatically updates its cache using pypi's changelog protocol


devpi-server is a WSGI application currently implemented with Bottle
and maintains caching state in Redis and the file system.


Getting started 
----------------------------

Simply install ``devpi-server`` via for example::

    pip install devpi-server

Make sure you have the ``redis-server`` binary available and issue::

    devpi-server

after which a http server is running on ``localhost:3141`` and you
can use the following index url with pip or easy_install::

    pip install -i http://localhost:3141/ext/pypi/simple/ ...
    easy_install -i http://localhost:3141/ext/pypi/simple/ ...

With pip, you can also set the environment variable
``PIP_INDEX_URL`` to ``http://localhost:3141/ext/pypi/simple/``
to avoid having to re-type the index url or put an according
entry in your ``.pip/pip.conf`` file.

By default, devpi-server configures and starts its own redis instance. 
In a production setting you might want to use the ``--redismode=manual``
option to control the setup of redis yourself.


command line options 
---------------------

A list of all devpi-server options::

    $ devpi-server -h


Project status and next steps
-----------------------------

``devpi-server`` is considered beta because it's just an initial release.

It is is tested through tox and has all of its automated pytest suite 
passing for python2.7 and python2.6 on Ubuntu 12.04.  

``devpi-server`` is actively developed and will see more releases in 2013,
in particular for supporting private indexes. You are very welcome
to join and contribute:

* mailing list: 
* repository: http://bitbucket.org/hpk42/devpi-server
* Bugtracker: http://bitbucket.org/hpk42/devpi-server/issues
