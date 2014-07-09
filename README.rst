devpi: PyPI server and packaging/testing/release tool
===================================================================

``devpi`` is a meta package installing two other packages:

- `devpi-server <http://pypi.python.org/pypi/devpi-server>`_: 
  for serving a pypi.python.org consistent
  caching index as well as local github-style overlay indexes.

- `devpi-web <http://pypi.python.org/pypi/devpi-web>`_: 
  plugin for devpi-server that provides a web and search interface

- `devpi-client <http://pypi.python.org/pypi/devpi-client>`_: 
  command line tool with sub commands for
  creating users, using indexes, uploading to and installing
  from indexes, as well as a "test" command for invoking tox.


For getting started see http://doc.devpi.net/

Holger Krekel, October 2013
