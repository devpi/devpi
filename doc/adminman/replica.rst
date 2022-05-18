devpi-server replication
====================================

.. versionadded:: 2.0

The devpi-server replication protocol aims to support:

- **ongoing incremental backup**: all state changes on the master
  are reflected in the replica with only a short delay

- **high-availability/failover**: when the master goes down, a replica
  node can be manually configured to be the new master.

- **faster installs**: a geographically closer replica will
  answer queries much faster than the more remote master node.

See also :ref:`serverstatus`.

Usage
---------------------------------------------

Any regular ``devpi-server`` instance can serve as a master. 
To turn a server into a master, enable the replication protocol by
providing the ``--role master`` option at startup::

    devpi-server --serverdir masterdir --role master

In order to start a replica you need to provide the root master URL::

    devpi-server --master-url http://url-of-master

The master and its replicas have to share the secret in the file specified with
``--secretfile "${DEVPISERVER_SECRETFILE}"``.

If you are testing replication and run the master and replica on the
same host make sure you specify different server directories and ports
like this::

    # start master in a shell
    devpi-server --serverdir masterdir --role master

    # start replica in another shell
    devpi-server --master-url http://localhost:3141 --port 4000 --serverdir replica

You can now connect to ``http://localhost:3141`` or ``http://localhost:4000``
interchangeably.  Specify ``--debug`` to see more output related to the
replica operations.


Implemented user stories
-------------------------------------------

The devpi-server replication protocol is designed with
the following user stories in mind:

- A user wants to connect to a geographically close devpi-server 
  instance (real-time "replica") and use it instead of the geographically 
  remote master devpi-server instance. The real-time replica serves the 
  same indices, releases and documentation that the master provides. 

- A user uploads to the replica server a package, documentation, test result 
  or modifies an index and expects the change to be visible at the master
  and other replicas.  The replica will proxy such operations to the master 
  and notify the user of a successful change only after the operation 
  propagated back to the replica.

- A user can repeat installations against a replica without requiring
  the master or ``https://pypi.org`` to be online.  The replica
  carries all necessary information with itself but it will not allow 
  any modifying operations without connecting to the master.

- A server administrator can start a devpi-server in replicating mode 
  by providing a master URL. The node will immediately start with replicating 
  the master information.  After the initial sync the replica keep
  a http connection to the master in order to get notified immediately of any
  changes.


.. _`Developer notes`:

Developer notes
-----------------------------------------------------------

The text below is useful for a developer that needs to get more information about the status of the implementation of the replica protocol.

.. _`http relaying`:

HTTP relaying of replica server to master
++++++++++++++++++++++++++++++++++++++++++++++++++++++++

devpi-server in replica mode serves the same API and endpoints 
as the master server.  In general any state-changing
requests will be relayed to the master which should in its success
code tell what serial this change refers to.  The replica server
can then return a success code to its client after
that serial has been synchronized successfully.  Other replicas
may or may not have synchronized the same change.


.. _`laptop replication`:

Laptop replication (frequent disconnects)
++++++++++++++++++++++++++++++++++++++++++++++++++++++++

The primary user story for replication as of version 2.0 is maintaining
a per-organisation multi-server install of devpi-server.  In principle,
a local per-laptop replica can use the same replication mechanisms.
As laptops are often disconnected or sleeping, the replication
pattern will look different: it will be more common to have relatively
large lists of change entries to process.

In the future, we can think about ways to minimize replication traffic by:

a) subscribing to changes based on a filter (only changes related to a user,
   certain indices, etc.)

b) only retrieving archive or documentation files into the replica
   if they are actually accessed on the laptop replica side.


Handling concurrency within the replica server
++++++++++++++++++++++++++++++++++++++++++++++++++++++++

Both master and replica servers can handle multiple concurrent requests.
HTTP requests are run in threads and we thus need to insure that the
backend layer is thread safe and provides means for manipulating state
in an atomic way.

One particular complication is `http relaying`_ of state changes posted
to the replica.  The replication thread needs to be able to signal
the request-thread which triggered the change on the master so that
a proper http response can be constructed.  Given a state-changing
request to the replica, we do the following:

- trigger state changing on the master, wait for success response
  which includes the related ``SERIAL``.

- wait for the replica state serial to reach at least ``SERIAL``.

- if the wait times out we return an error result.

Note that this sequence could be interrupted at any point in time
because of a partial network disconnect or a failure between the three 
parties (replica, master, client).  This may make it hard for the
client to know the exact result of the original state-changing operation.  

To remedy this, we may in the future consider implementing a per-server
(and maybe also per-index) view on "recent changes", and also detailing
the "local" serials and "remote serials" as well as the replica/master
connection status, see `issue113
<https://github.com/devpi/devpi/issue/113/provide-devpi-url-status-to-retrieve>`_.


Transactional master state changes / SQL
++++++++++++++++++++++++++++++++++++++++++++++++++++++++

Every change on the devpi-server master side happens
with `ACID guarantees <http://en.wikipedia.org/wiki/ACID>`_
and is associated with an incrementing serial number.  
All changes to meta information happen in a transaction
carried out via ``sqlite3``.  Files are stored in the
filesystem outside of the SQL database.


SSL support (experimental)
++++++++++++++++++++++++++++++++++++++++++++++++++++++++

A replica can send a client certificate with the ``--replica-cert`` option.
You need to provide a pem file which contains the certificate and the key.
The key must not have a passphrase, currently new request sessions may be
created at any time which would require entering the passphrase.

If you use a self signed server certificate or if your certificate authority
isn't supported, you can use the ``REQUESTS_CA_BUNDLE`` environment variable
to specify the server certificate file to use.
