
server Replication protocol (DRAFT)
====================================

The devpi-server replication protocol aims to:

- support high-availability: when the master goes down, a replica
  node can be taken as the new master.

- support faster installs: a geographically closer replica will
  answer queries much faster than the more remote master node.

The devpi-server replication protocol is designed with
the following user stories in mind:

- User wants to connect to a geographically close devpi-server 
  instance (real-time "replica") and use it instead of the geographically 
  remote master devpi-server instance. The real-time replica serves the 
  same indices, packages and documentation that the master provides. 

- user uploads to the replica server a package, documentation, test result 
  or modifies an index and expects the change to be visible at the master
  and other replicas.  The replica will proxy such operations to the master 
  and notify the user of a successful change only after the operation 
  propagated back to the replica.  A user's authentication against 
  a mirror is handled by relaying it to the master as well.

- A server administrator can start a devpi-server in replicating mode 
  by providing a master URL. The node will start with replicating 
  the master information. During the initial replica/master synchronization 
  the replica will not answer network requests.  After the initial sync
  the replica maintains a connection to the master in order to get 
  notified immediately of any changes.

we maintain the following functional properties and considerations:

- When a package or index on the master changes the replica receives the 
  changes within a minute so that the user can access them locally. 

- High availability is only required for installation activities. 
  This implies that we:
  1. could handle Authentication by the master only. If the master is down, 
     users will not be able to authenticate until the master is back online. 
     This also implies that authentication should occur by proxy (relay) 
     via replicas.

  2. Release file upload is also done by proxying it to the master. 
     Performance/robustness is not required for upload operations as the
     primary goal behind mirrors is to provide a fast and reliable mechanism
     to deploy test systems.


Replication Protocol outline
------------------------------------------

For replicating changes from master to replica:

- Every server-state change is logged to a **changelog** where
  each entry is associated to exactly one serial.

- A replica maintains its own serial (starting at ``0``) and asks
  the master for the changelog entries since that serial.  For each
  such changelog entry it changes the replica state and then 
  increments its own serial.

So the replica uses an RPC-API like this::

    changelog_since_serial(since_serial) -> list of change entries
   
More precisely, we have the following change entry types:

- ``RESOURCE create/modify/delete`` where resource can be 
  a user, an index config, a project config, or a versionconfig.
  resource changes can be be fully transported with each changelog
  entry because they rarely exceed 1K (except for versionconfigs
  which contain release-registration metadata, itself containing
  the long description which can be a few Ks).

- ``release archive upload``: an upload of a release file related
  to a specific USER/INDEX/PROJECT/VERSION.

- ``documentation archive upload``: an upload of a documentation zip
  file related to a specific USER/INDEX/PROJECT/VERSION.

- ``test resultlog upload``: an upload of a test result file
  related to a specific MD5/archive

- ``[pypimirror] pypi project metadata``: metadata about a pypi project

- ``[pypimirror] release archive``: a release file mirrored from
  pypi.python.org, related to a project/version

The change entries marked with ``[pypimirror]`` are special because
server-state changes are triggered by just accessing projects on
the ``/root/pypi`` mirror.   Including pypi-changes in the replication
protocol will increase replication traffic considerably, see also the
discussion about `laptop replication`_.

.. _`http relaying`:

HTTP relaying of replica server to master
-----------------------------------------------------------

devpi-server in replica mode serves the same API and endpoints 
as the master server but it will internally relay change-operations
(see change entry types above).  In general such state-changing
requests will be relayed to the master which should in its success
code tell what serial this change refers to.  The replica server
can then return a success code to its client after
that serial has been synchronized successfully.  Other replicas
may or may not have synchronized the same change.


.. _`laptop replication`:

Laptop replication (frequent disconnects)
------------------------------------------------

The primary user story for replication is maintaining a per-organisation
multi-server install of devpi-server.  In principle, a local per-laptop
replica can use the same replication mechanisms, however.  As laptops
are often disconnected or sleeping, the replication pattern will look
different: it will be more common to have relatively large
lists of change entries to process.

In the future, we can think about ways to minimize replication traffic by:

a) subscribing to changes based on a filter (only changes related to a user,
   certain indices, etc.)

b) only retrieving archive or documentation files into the replica
   if they are actually accessed on the replica side.


Handling concurrency within the replica server
-------------------------------------------------

Both master and replica servers can handle multiple concurrent requests.
HTTP requests are run in threads (or greenlets) and we thus need to insure
that the backend layer is thread safe and provides means for
manipulating state in an atomic way.

One particular complication is `http relaying`_ of state changes posted
to the replica.  The replication thread needs to be able to signal
the request-thread which triggered the change on the master so that
a proper http response can be constructed.  Given a state-changing
request to the replica, we can do the following:

- trigger state changing on the master, wait for success response
  which includes the related ``SERIAL``.

- wait for the replica state serial to reach at least ``SERIAL``.

- if the wait times out we need to return a 408/timeout or
  504/GATEWAYTIMEOUT response code. 

Note that this sequence could be interrupted at any point in time
because of a partial network disconnect or a failure between the three 
parties (replica, master, client).  This may make it hard for the
client to know the exact result of the original state-changing operation.  
To remedy this, we consider implementing a per-server (and maybe also
per-index) view on "recent changes", and also detailing the "local" serials
and "remote serials" as well as the replica/master connection status.

