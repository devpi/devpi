devpi: PyPI server and packaging/testing/release tool
=================================================================


.. note::

  Please note that devpi-server 4.0.0 is a bug fix/compatibility release as it
  only changes project name normalization compared to 3.1.x. The internal use
  of the normalization requires an export/import cycle, which is the reason for
  the major version increase. There are no other big changes and so everyone
  who used devpi-server 3.x.y should be fine just using 4.0.0. It's also fine
  to export from 2.6.x and import with 4.0.0.

  See :doc:`announce/server-4.0` for details.


.. include:: links.rst

.. sidebar:: Links and contact

   `issue tracker <https://bitbucket.org/hpk42/devpi/issues>`_, `mailing list <https://groups.google.com/d/forum/devpi-dev>`_

   :ref:`tutorials and documentation <label_quickstart_section>`
   
   `repo of server/web/client <https://bitbucket.org/hpk42/devpi/>`_

   #devpi on freenode

The MIT-licensed devpi system features a powerful PyPI-compatible server
and a complimentary command line tool to drive packaging, testing and
release activities with Python.  Main features and usage scenarios:

- **fast PyPI mirror**: use a local self-updating pypi.python.org 
  caching mirror which works with ``pip`` and ``easy_install``.  
  After files are first requested can work off-line and will 
  try to re-check with pypi every 30 minutes by default.
  Since version 3.0 you can :ref:`generically mirror from pypi-compatible
  servers <mirror_index>`.  See :doc:`quickstart-pypimirror`.

- **uploading, testing and staging with private indexes**: upload Python archives and 
  documentation to your own indexes.  Trigger testing of your uploaded release files 
  with tox_ and record them with each release file.  When ready push your
  successfully tested release files and documentation
  to another index (staging) or to pypirc-configured external 
  indexes such as https://pypi.python.org . See :doc:`quickstart-releaseprocess`.

- **index inheritance**: Each index can inherit packages from another
  index, including the pypi cache ``root/pypi``.  This allows to 
  have development indexes that also contain all releases from a production
  index.  All privately uploaded packages will by default inhibit lookups 
  from pypi, allowing to stay safe from an attacker who could otherwise
  upload malicious release files to the public PyPI index.

- **web interface and search**: By installing the :doc:`adminman/web`
  plugin package you can navigate indexes and search through release metadata
  and documentation of your private indexes.

- **replication**: Keep one or more real-time
  :doc:`replica <adminman/replica>` to speed up access, keep a failover server
  and to distribute the devpi system across your organisation.
  There is :doc:`json status information <adminman/server-status>`
  about master/replica sites for monitoring.

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
   :maxdepth: 2

   quickstart-pypimirror
   quickstart-releaseprocess
   quickstart-server

   userman/index
   adminman/index
   devguide/index

.. toctree::
   :maxdepth: 1

   status
   glossary
   announce/index
   changelog

.. toctree::
   :hidden:

   links
   curl

.. 
    Indices and tables
    ==================

    * :ref:`genindex`
    * :ref:`modindex`
    * :ref:`search`

