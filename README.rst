devpi: PyPI server and packaging/testing/release tool
===================================================================

This repository contains three packages comprising the core devpi system
on the server and client side:

- `devpi-server <https://pypi.org/project/devpi-server/>`_:
  for serving a pypi.org consistent
  caching index as well as user or team based indexes
  which can inherit packages from each other or from
  the pypi.org site.

- `devpi-web <https://pypi.org/project/devpi-web/>`_:
  plugin for devpi-server that provides a web and search interface

- `devpi-client <https://pypi.org/project/devpi-client/>`_:
  command line tool with sub commands for
  creating users, using indexes, uploading to and installing
  from indexes, as well as a "test" command for invoking tox.

For getting started, more docs see https://doc.devpi.net/

Holger Krekel, Florian Schulze, April 2017
(contact us at office at merlinux.eu for support contracts
and paid help)
