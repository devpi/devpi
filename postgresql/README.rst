devpi-postgresql: a PostgreSQL storage backend for devpi-server
===============================================================

.. warning::
    This plugin is considered experimental!

This plugin adds a PostgreSQL storage backend for `devpi-server`_.

.. _devpi-server: http://pypi.python.org/pypi/devpi-server


Installation
------------

``devpi-postgresql`` needs to be installed alongside ``devpi-server``.

You can install it with::

    pip install devpi-postgresql


Usage
-----

When using the PostgreSQL storage, ``devpi-server`` expects an empty database.
You have to create one like this: ``createdb devpi``

Upon first initialization of ``devpi-server`` use ``--storage pg8000`` to select the PostgreSQL backend.

By default it'll use the ``devpi`` database on ``localhost`` port ``5432``.
To change that, use ``storage pg8000:host=example.com,port=5433,database=devpi_prod``.

All user/index files and metadata of ``devpi-server`` are stored in the database.
A few things and settings are still stored as files in the directory specified by ``--serverdir``.

Plugins like ``devpi-web`` don't or can't use the storage backend.
They still handle their own storage.
