
.. include:: links.rst

.. _serverstatus:

Server Status information
----------------------------------------

.. versionadded:: devpi-server-2.1.0

You can check the ``/+status`` to obtain status and configuration
information about a running server::

    role:  MASTER|REPLICA
    uuid: UUID of instance
    host: host this server is listening on
    port: port this server is listening on
    outside-url: nill|url this host is meant to be accessed from
    serverdir: local path to serverdir 
  
Master nodes also provide a list of replicas::
 
    replicas: list of replica dicts each of which looks like this:
        uuid: uuid of replica server
        client-addr: address from which replication polling happens/happened
        last-polled: 0 (seconds ago)
        last-serial: NUM

Replica nodes also provide extra information related to their master:

    master-url: URL of master if we are a replica
    master-uuid: uuid of master
    master-serial: last known serial the master has


UUIDs of master and replica sites
-------------------------------------------------------------

On initial startup, each devpi-server instance generates a UUID which it
returns through a ``X-DEVPI-SERVER-UUID`` HTTP header.  When operating as
a replica, the remote master's UUID is interally stored as well and compared
for consistency on subsequent requests.


