devpi-server: on-demand deep pypi.python.org cache
===========================================================

devpi-server is **meant to be run in company environments**
which want to speed up and robustify installing Python packages.

devpi-server acts as a caching proxy frontend for pypi.python.org
and provides features not found in any other PyPI server:

- caches index and release file information including
  those from 3rd party sites and "#egg=" development eggs

- allows pip/easy_install/buildout to avoid all client-side crawling,
  thus providing lightning-fast and offline installation the second
  time you install a project

- automatically updates its cache using pypi's changelog protocol


.. warning::

    Do not run devpi-server openly on the internet without consulting
    a lawyer because its caching functionality might be seen as 
    "re-distribution" if everyone can access it for which you may 
    not have the appropriate rights.

devpi-server is a WSGI application currently implemented with Bottle
and maintains caching state in Redis and the file system.


Getting started 
----------------------------

Simply install ``devpi-server`` via for example::

    pip install devpi-server

Make sure you have ``redis`` installed and issue::

    devpi-server

after which a http server is running on ``localhost:3141`` and you
can use this index url with pip or easy_install::

    pip install -i http://localhost:3141/ext/pypi/simple/ ...
    easy_install -i http://localhost:3141/ext/pypi/simple/ ...

The redis server will by default run on port 6400.


Project status and next steps
-----------------------------

``devpi-server`` is considered beta because it's a first release
and has so far only been used by its author :)

``devpi-server`` is tested through tox and has all of its automated 
pytest suite passing for python2.7 and python2.6 on Ubuntu 12.04.  
It should only require a little bit of effort to make it work on python3.

``devpi-server`` is actively developed and will see more releases in 2013,


Contact points
---------------

mailing list: XXX
repository: http://bitbucket.org/hpk42/devpi-server
Bugtracker: http://bitbucket.org/hpk42/devpi-server/issues


