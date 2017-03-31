devpi: PyPI server and packaging/testing/release tool
===================================================================

This repository contains three packages comprising the core devpi system 
on the server and client side:

- `devpi-server <http://pypi.python.org/pypi/devpi-server>`_: 
  for serving a pypi.python.org consistent
  caching index as well as user or team based indexes
  which can inherit packages from each other or from
  the pypi.python.org site.

- `devpi-web <http://pypi.python.org/pypi/devpi-web>`_: 
  plugin for devpi-server that provides a web and search interface

- `devpi-client <http://pypi.python.org/pypi/devpi-client>`_: 
  command line tool with sub commands for
  creating users, using indexes, uploading to and installing
  from indexes, as well as a "test" command for invoking tox.

For getting started, more docs see http://doc.devpi.net/

.. note::

    The "devpi" pypi metapackage is obsolete, don't use it anymore.

Holger Krekel, Feb 2015