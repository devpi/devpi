.. _label_userman_devpi_install_chapter:

Uploading, testing and pushing packages
=======================================

.. include:: ../links.rst

.. sidebar:: Summary
    
    This chapter ilustrates how to term:`upload`, test and :term:`push` a package 
    between indexes or to an external index server such as https://pypi.python.org.

    *related commands*:
      * :ref:`cmdref_upload`
      * :ref:`cmdref_push` 
      * :ref:`cmdref_test`
      * :ref:`cmdref_install`

Overview
--------

As explained in the :ref:`label_userman_concepts_chapter` chapter, the **/root/pypi** is a special cache to 
http://python.pypi.org. 

This section shows how open source packages (e.g. pytest) can be installed 
using a user index (**/emilie/dev**) which has the following inheritance tree::

      /root/pypi
          ^
          |
      /emilie/dev
      

Sample Package
^^^^^^^^^^^^^^

The sample project consists of the following files:

   * :download:`pysober.py <./pysober/pysober.py>` The module to be released.
   * :download:`setup.py <./pysober/setup.py>` 
   * :download:`MANIFEST.in <./pysober/MANIFEST.in>` 
   * :download:`tox.ini <./pysober/tox.ini>` Tox configuration file required by **devpi** :ref:`cmdref_test`
   * :download:`./test/conftest.py <./pysober/test/conftest.py>` Adds a --project-version option
   * :download:`./test/test_pysober.py <./pysober/test/test_pysober.py>`
   * :download:`./doc/Makefile <./pysober/doc/Makefile>` The documentation project which looks like this :ref:`pysober_index`
   * :download:`./doc/source/overview.rst <./pysober/doc/source/overview.rst>`
   * :download:`./doc/source/index.rst <./pysober/doc/source/index.rst>`
   * :download:`./doc/source/conf.py <./pysober/doc/source/conf.py>`

      
XXX Creating a virtual environment
----------------------------------

This step is presented here to simply create a sandbox using `virtualenv`_::

   $ devpi install --venv sandbox
   --> $ virtualenv sandbox
   New python executable in sandbox/bin/python
   Installing setuptools............done.
   Installing pip...............done
   
   



