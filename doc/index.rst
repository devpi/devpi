devpi: PyPI server and packaging/testing/release tool
=================================================================


.. note::

  See :ref:`how to update your pre devpi-server 4.5.0 PyPI mirror indexes for pypi.org <label_server_4_5>`.

.. include:: links.rst

.. sidebar:: Links and contact

   `issue tracker <https://github.com/devpi/devpi/issues>`_,
   `mailing list <https://mail.python.org/mm3/mailman3/lists/devpi-dev.python.org/>`_

   :ref:`tutorials and documentation <label_quickstart_section>`
   
   `repo of server/web/client <https://github.com/devpi/devpi/>`_

The MIT-licensed devpi system features a powerful PyPI-compatible server
and a complementary command line tool to drive packaging, testing and
release activities with Python.  Main features and usage scenarios:

- **fast PyPI mirror**: use a local self-updating pypi.org
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
  indexes such as https://pypi.org . See :doc:`quickstart-releaseprocess`.

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
   contributing
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

