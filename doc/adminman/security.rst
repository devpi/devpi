devpi-server security
=====================

.. warning::

    By default exposing devpi-server to the internet is not safe!

Look into :ref:`devpi_um_restrict_user_creation` to prevent everyone from
being able to create their own user account on your server.

For :doc:`replication <replica>` devpi-server exposes the ``/+changelog``
route. If replication isn't used this should be blocked. Otherwise your whole
server can be replicated from the outside, including the password hashes of
all users. This includes deleted users until an
:ref:`export/import cycle <upgrade>` has been made.
