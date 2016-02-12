devpi-{server,web}-3.0 releases: generalized mirroring, speed, descriptions
============================================================================

The 3.0 releases of devpi-server and devpi-web, the python packaging and 
work flow system for handling release files, documentation, testing and staging,
bring several major improvements:

- Due to popular demand we now support generalized mirroring, i.e. you can 
  create mirror indexes which proxy and cache release files from other pypi 
  servers.  Even if the mirror goes down, pip-installing will continue to work
  with your devpi-server instance.  Previously we only supported mirroring 
  of pypi.python.org.  Using it is simple:
  http://doc.devpi.net/3.0/userman/devpi_indices.html#mirror-index

- For our enterprise clients we majorly worked on improving the speed
  of serving simple pages which is now several times faster with
  private indexes.  We now also support multiple worker processes
  both on master and replica sites.
  http://doc.devpi.net/3.0/adminman/server.html#multiple-server-instances

- For our enterprise clients we also introduced a new backend
  architecture which allows to store server state in sqlite or
  postgres (which is supported through a separately released plugin).
  The default remains to use the "sqlite" backend and store files
  on the filesystem. See
  http://doc.devpi.net/3.0/adminman/server.html#storage-backend-selection

- we started a new "admin" manual for devpi-server which describes
  features relating to server configuration, replication and security
  aspects.  It's a bit work-in-progress but should already be helpful.
  http://doc.devpi.net/3.0/adminman/

- A few option names changed and we also released devpi-client-2.5 
  where we took great care to keep it forward and backward compatible
  so it should run against devpi-server-2.1 and upwards all the way
  to 3.0.

- The "3.0" major release number increase means that you will need to run 
  through an export/import cycle to upgrade your devpi-2.X installation.

For more details, see the changelog and the referenced documentation
with the main entry point here:

    http://doc.devpi.net

Many thanks to my partner Florian Schulze and to the several companies
who funded parts of the work on 3.0.  We are especially grateful for
their support to not only cover their own direct issues but also support
community driven demands.  I'd also like to express my gratitude to
Rackspace and Jesse Noller who provide VMs for our open source work and
which help a lot with the testing of our releases.

We are open towards entering more support contracts to make sure you get
what you need out of devpi, tox and pytest which together provide a
mature tool chain for professional python development.  And speaking of
showing support, if you or your company is interested to donate to or
attend the largest python testing sprint in history with a particular
focus to pytest or tox, please see

    https://www.indiegogo.com/projects/python-testing-sprint-mid-2016/

have fun,

holger krekel, http://merlinux.eu



server-3.0.0 (2016-02-12)
-------------------------

- dropped support for python2.6

- block most ascii symbols for user and index names except ``-.@_``.
  unicode characters are fine.

- add ``--no-root-pypi`` option which prevents the creation of the
  ``root/pypi`` mirror instance on first startup.

- added optional ``title`` and ``description`` options to users and indexes.

- new indexes have no bases by default anymore. If you want to be able to
  install pypi packages, then you have to explicitly add ``root/pypi`` to
  the ``bases`` option of your index.

- added optional ``custom_data`` option to users.

- generalized mirroring to allow adding mirror indexes other than only PyPI

- renamed ``pypi_whitelist`` to ``mirror_whitelist``

- speed up simple-page serving for private indexes. A private index
  with 200 release files should now be some 5 times faster.

- internally use normalized project names everywhere, simplifying
  code and slightly speeding up some operations.

- change {name} in route_urls to {project} to disambiguate.
  This is potentially incompatible for plugins which have registered
  on existing route_urls.

- use "project" variable naming consistently in APIs

- drop calling of devpi_pypi_initial hook in favor of
  the new "devpi_mirror_initialnames(stage, projectnames)" hook
  which is called when a mirror is initialized.

- introduce new "devpiserver_stage_created(stage)" hook which is
  called for each index which is created.

- simplify and unify internal mirroring code some more
  with "normal" stage handling.

- don't persist the list of mirrored project names anymore
  but rely on a per-process RAM cache and the fact
  that neither the UI nor pip/easy_install typically
  need the projectnames list, anyway.

- introduce new "devpiserver_storage_backend" hook which allows plugins to
  provide custom storage backends. When there is more than one backend
  available, the "--storage" option becomes required for startup.

- introduce new "--requests-only" option to start devpi-server in
  "worker" mode.  It can be used both for master and replica sites.  It
  starts devpi-server without event processing and replication threads and
  thus depends on respective "main" instances (those not using
  "--request-only") to perform event and hook processing.  Each
  worker instance needs to share the filesystem with a main instance.
  Worker instances can not serve the "/+status" URL which must
  always be routed to the main instance.

- add more info when importing data.  Thanks Marc Abramowitz for the PR.


web-3.0.0 (2016-02-12)
----------------------

- dropped support for python2.6

- index.pt, root.pt, style.css: added title and description to
  users and indexes.

- root.pt, style.css: more compact styling of user/index overview using
  flexbox, resulting in three columns at most sizes

- cleanup previously unpacked documentation to remove obsolete files.

- store hash of doczip with the unpacked data to avoid unpacking if the data
  already exists.

- project.pt, version.pt: renamed ``pypi_whitelist`` related things to
  ``mirror_whitelist``.

- require and adapt to devpi-server-3.0.0 which always uses
  normalized project names internally and offers new hooks.
  devpi-web-3.0.0 is incompatible to devpi-server-2.X.

- doc.pt, macros.pt, style.css, docview.js: use scrollbar of documentation
  iframe, so documentation that contains dynamically resizing elements works
  correctly. For that to work, the search from and navigation was moved into a
  wrapping div with class ``header``, so it can overlap the top of the iframe.


2.5.0 (2016-02-08)
------------------

- the ``user`` command now behaves slightly more like ``index`` to show
  current user settings and modify them.

- fix issue309: print server versions with ``devpi --version`` if available.
  This is only supported on Python 3.x because of shortcomings in older
  argparse versions for Python 2.x.

- fix issue310: with --set-cfg the ``index`` setting in the ``[search]``
  section would be set multiple times.

- fix getjson to work when no index but a server is selected

- allow full urls for getjson

- "devpi quickstart" is not documented anymore and will be removed
  in a later release.

