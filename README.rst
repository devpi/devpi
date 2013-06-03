devpi: managing and serving Python release processes
=====================================================

This is the home for devpi-server and the devpi command line client,
see the server/ and client/ sub directories:

- server: contains devpi-server for serving PyPI indexes including
  a selective auto-updating pypi.python.org mirror index.

- client: contains command line tools with sub commands for
  creating users, using indexes, uploading to and installing
  from indexes, as well as a "test" command for invoking tox.
