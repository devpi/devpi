devpi: PyPI-compatible server and complimentary command line tool
=================================================================

.. include:: links.rst

.. sidebar:: Meta

   `issue tracker <https://bitbucket.org/hpk42/devpi/issues>`_

   `mailing list <https://groups.google.com/d/forum/devpi-dev>`_

   #devpi on freenode


The MIT-licensed devpi system features a powerful PyPI-compatible server
and a complimentary command line tool to drive packaging, testing and
release activities with Python.  Main features and usage scenarios:

- **fast PyPI mirror**: use a local self-updating pypi.python.org 
  caching mirror from pip_ or easy_install_.  After an initial cache-fill
  it can work off-line and will re-synchronize when you get online again.

- **staging and release management**: push releases and files 
  from one index to another ("dev -> prod").  Use "non-volatile"
  indexes to prevent a release or release file from disappearing
  or changing.  

- **test recording**: run tests via tox_ and attach test results 
  to a specific release file.  Inspect test results on a per-release
  file basis before you decide to push it to https://pypi.python.org

- **index inheritance**: configure an index to transparently
  include all packages from one or more base indices.  Typically,
  your index will at least inherit all pypi.python.org packages so 
  that all dependencies will resolve when installing your own
  (previously uploaded) development package from an index.

To learn more checkout our quickstart and other docs.

To understand more of how the PyPI protocol works, 
checkout :pep:`438` and related documentation

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

   curl
   
   glossary


.. toctree::
   :hidden:

   links


.. 
    Indices and tables
    ==================

    * :ref:`genindex`
    * :ref:`modindex`
    * :ref:`search`

