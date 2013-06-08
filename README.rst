devpi: managing and serving Python release processes
===================================================================

``devpi`` is a meta package installing two other packages::

- ``devpi-server``: for serving a pypi.python.org consistent
  caching index as well as local github-style overlay indexes.

- ``devpi-client``: command line tool with sub commands for
  creating users, using indexes, uploading to and installing
  from indexes, as well as a "test" command for invoking tox.

For getting started see http://doc.devpi.net/

Holger Krekel, June 2013
