===============================================================
devpi-postgresql: a PostgreSQL storage backend for devpi-server
===============================================================

This plugin adds a PostgreSQL storage backend for `devpi-server`_.

.. _devpi-server: https://pypi.org/project/devpi-server/


Installation
============

``devpi-postgresql`` needs to be installed alongside ``devpi-server``.

You can install it with::

    pip install devpi-postgresql


Requirements
============

At least PostgreSQL 9.5 is required for ``ON CONFLICT`` support.


Usage
=====

When using the PostgreSQL storage, ``devpi-server`` expects an empty database.
You have to create one like this: ``createdb devpi``
Depending on your PostgreSQL setup you have to create a user and grant it permissions on the new database like this::

    CREATE ROLE devpi WITH LOGIN;
    GRANT CREATE, CONNECT ON DATABASE devpi TO devpi;

Upon first initialization of ``devpi-server`` use ``--storage pg8000`` to select the PostgreSQL backend.

By default it'll use the ``devpi`` database on ``localhost`` port ``5432``.
To change that, use ``storage pg8000:host=example.com,port=5433,database=devpi_prod``.
The possible settings are: ``database``, ``host``, ``port``, ``unix_sock``, ``user``, ``password``, ``ssl_check_hostname``, ``ssl_ca_certs``, ``ssl_certfile`` and ``ssl_keyfile``.

If any of the "ssl" settings is specified, a secure Postgres connection will be made. Typically, the name of a file containing a certificate authority certificate will need to be specified via ``ssl_ca_certs``. By default, the server's hostname will be checked against the certificate it presents. Optionally disable this behavior with the ``ssl_check_hostname`` setting.  Use ``ssl_certfile`` and ``ssl_keyfile`` to enable certificate-based client authentication.

All user/index files and metadata of ``devpi-server`` are stored in the database.
A few things and settings are still stored as files in the directory specified by ``--serverdir``.

Plugins like ``devpi-web`` don't or can't use the storage backend.
They still handle their own storage.


Support
=======

If you find a bug, use the `issue tracker at Github`_.

For general questions use `GitHub Discussions`_ or the `devpi-dev@python.org mailing list`_.

For support contracts and paid help contact ``mail at pyfidelity.com``.

.. _issue tracker at Github: https://github.com/devpi/devpi/issues/
.. _devpi-dev@python.org mailing list: https://mail.python.org/mailman3/lists/devpi-dev.python.org/
.. _GitHub Discussions: https://github.com/devpi/devpi/discussions
