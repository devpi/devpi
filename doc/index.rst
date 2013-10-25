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

- **uploading and staging**: upload ``setup.py``-style packages 
  to a private index.  Test your uploaded release files and, when 
  ready, push them verbatim from one internal index to another (staging).
  You can configure on a per-index basis who can upload.  Special 
  "push" syntax is available for pushing a release and its files 
  from an internal to an external index (such as https://pypi.python.org ), 
  dramatically reducing the risk of release accidents. 

- **index inheritance**: configure an index to transparently
  include all releases/packages from one or more internal base indices.  
  For example, you can install internal or development packages from
  your own internal index; if that index inherits from the internal
  read-only ``root/pypi`` pypi.python.org-caching index, all your 
  pypi-dependencies will resolve correctly.

- **test recording**: devpi can run tests via tox_ and attach test results 
  to a specific release file.  Inspect test results on a per-release
  file basis before you decide to push it to an external index.

- **Jenkins integration**: You can :ref:`easily set a per-index Jenkins
  trigger <jenkins integration>` for automatically tox-testing any 
  uploaded release file and query releases for their test results.

To learn more checkout our quickstart and other docs.

.. _label_quickstart_section:

Tutorials and Documentation
-----------------------------------------

.. toctree::
   :maxdepth: 1

   quickstart-pypimirror
   quickstart-releaseprocess
   quickstart-server

   status

   userman/index

   
   glossary


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

