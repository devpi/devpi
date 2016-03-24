devpi-server administration
====================================


.. _upgrade:

versioning, exporting and importing server state
----------------------------------------------------

.. note::

    you don't need to perform any explicit data migration if you are 
    using devpi-server as a pure pypi mirror, i.e. not creating
    users or uploading releases to indexes.  devpi-server
    will automatically wipe and re-initialize the pypi cache 
    in case of incompatible internal data-layout changes.

``devpi-server`` maintains its state in a ``serverdir``,
by default in ``$HOME/.devpi/server``, unless you specify
a different location via the ``--serverdir`` option.

You can use the ``--export`` option to dump user and index state
into a directory::

    devpi-server --export dumpdir

``dumpdir`` will then contain a ``dataindex.json`` and the
files that comprise the server state.

Using the same version of ``devpi-server`` or a future release you can
then import this dumped server state::

    devpi-server --serverdir newserver --import dumpdir

This will import the previously exported server dump and
create a new server state structure in the ``newserver`` directory.
You can then run a server from this new state::

    devpi-server --serverdir newserver --port 5000

and check through a browser that all your data got migrated correctly.
Once you are happy you can remove the old serverdir.

.. note::

    Only your private indexes are fully exported and can be imported.
    For mirror indexes only the settings are exported, cached files are
    left out.


restricting modification rights
-------------------------------

You can use the ``--restrict-modify`` option of ``devpi-server`` to restrict
who can create, modify and delete users and indices.


multi-process high-performance setups
-------------------------------------

.. versionadded: 3.0

You can run multiple processes both on master and replica sites if you want
to improve throughput.  On the master and each replica site you need to
run a single "main" instance which will care for event and hook processing 
(needed e.g. for running devpi-web) and you can then start one or more
workers like this::

    devpi-server --requests-only  --port NUM # add other options as needed

This "worker" startup will only process web requests (both read and write)
but it will not run event based hooks but rather rely on the respective main instance
to do that.  Therefore workers accept uploads, satisfy "pip install" requests
and can serve documentation (which is generated from the main instance) but a worker
will not function well if the main instance is absent.

Typically you will need to have a web-server like nginx which distributes load
to the main instance and the workers evenly.  Note that you need to make sure
that the ``/+status`` url is routed to a main instance because workers
will not be able to represent the status.


storage backend selection
-------------------------

.. versionadded: 3.0

.. warning::

    This is experimental and not well tested in production yet, use at your
    own risk.

The storage for user and index data can be changed by plugins. One example is
the `devpi-postgresql`_ plugin. It stores all the metadata and the package
files in a PostgreSQL database.

There are still some files in the directory specified with ``--serverdir``, for
example the server settings including the backend. Several plugins like
``devpi-web`` also still store their data in that directory, because the can't
use the storage backend for various reasons.

The storage backend can be selected and configured with the ``--storage``
option. As an example for ``devpi-postgresql``::

    devpi-server --serverdir newserver --storage pg8000:host=example.com


multiple server instances
-------------------------

.. versionadded: 3.0

.. warning::

    This is experimental and not well tested in production yet, use at your
    own risk. Maybe a :doc:`replica setup <replica>` is the better option.

To improve the performance of ``devpi-web``, there is an option to run
additional instances. They can be started with the ``--requests-only`` option.
There **can** *and* **must** be only one instance which runs without
``--requests-only``.

.. warning::

    The default sqlite storage backend can only have one writer, so the
    additional instances can only be used for web views and search, not for
    package downloads and uploads, as that can cause write conflicts. Any
    access to mirror indexes causes writes whenever the caches are updated.
    With a storage backend like `devpi-postgresql`_, which allows multiple
    writers, this limitation goes away.

For this to work, the ``--serverdir`` needs to be shared between all instances.
This can either be done on the same physical server by using the same
``--serverdir`` for all instances, or via a network filesystem.

The reason why all instances but one have to run with the ``--requests-only``
option are the event notification hooks. The event hooks are needed for
updating the search index, unpacking docs and rendering package descriptions
etc. If all instances would run them, they would cause write conflicts in the
shared storage.

.. _devpi-postgresql: http://pypi.python.org/pypi/devpi-postgresql
