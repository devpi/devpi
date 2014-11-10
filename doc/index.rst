devpi: PyPI server and packaging/testing/release tool
=================================================================

.. include:: links.rst

.. sidebar:: Links and contact

   `issue tracker <https://bitbucket.org/hpk42/devpi/issues>`_, `mailing list <https://groups.google.com/d/forum/devpi-dev>`_

   :ref:`tutorials and documentation <label_quickstart_section>`
   
   :doc:`changelog`

   #devpi on freenode

The MIT-licensed devpi system features a powerful PyPI-compatible server
and a complimentary command line tool to drive packaging, testing and
release activities with Python.  Main features and usage scenarios:

- **fast PyPI mirror**: use a local self-updating pypi.python.org 
  caching mirror which works with ``pip`` and ``easy_install``.  
  After an initial cache-fill it can work off-line and will 
  re-synchronize when you get online again.

- **uploading, testing and staging**: upload Python archives and documentation
  to private indexes.  Trigger testing of your uploaded release files 
  with tox_ and record them with each release file.  When ready push your
  successfully tested release files and documentation
  to another index (staging).  You can also push a release 
  to an external index such as https://pypi.python.org .

- **index inheritance**: Each index can inherit packages from another
  index, including the pypi cache ``root/pypi``.  This allows to 
  have development indexes that also contain all releases from a production
  index.  All privately uploaded packages will by default inhibit lookups 
  from pypi, allowing to stay safe from an attacker who could otherwise
  upload malicious release files to the public PyPI index.

- **web interface and search**: (New with 2.0) By installing the :doc:`web`
  plugin package you can navigate indexes and search through release metadata
  and documentation.

- **replication**: (new with 2.0) Keep one or more real-time
  :doc:`replica <replica>` to speed up access, keep a failover server
  and to distribute the devpi system across your organisation.
  (new with 2.1) :doc:`json status information <server-status>` 
  about master/replica sites.

- **importing/exporting**: To :ref:`upgrade <upgrade>` to a newer version, 
  devpi-server
  supports exporting server state from an old version and importing that
  from a new devpi-server version.

- **Jenkins integration**: You can :ref:`set a per-index Jenkins
  trigger <jenkins integration>` for automatically tox-testing any 
  uploaded release file and query releases for their test results.

To learn more, checkout our quickstart and other docs.

.. _label_quickstart_section:

Tutorials and Documentation
-----------------------------------------

.. toctree::
   :maxdepth: 1

   quickstart-pypimirror
   quickstart-releaseprocess
   quickstart-server

   web
   replica
   hooks
   status

   userman/index

   announce/index
   
   glossary

   devguide/index


.. toctree::
   :hidden:

   links
   curl
   changelog

.. 
    Indices and tables
    ==================

    * :ref:`genindex`
    * :ref:`modindex`
    * :ref:`search`

