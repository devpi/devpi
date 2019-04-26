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
The possible settings are: ``database``, ``host``, ``port``, ``unix_sock``, ``user`` and ``password``

All user/index files and metadata of ``devpi-server`` are stored in the database.
A few things and settings are still stored as files in the directory specified by ``--serverdir``.

Plugins like ``devpi-web`` don't or can't use the storage backend.
They still handle their own storage.
