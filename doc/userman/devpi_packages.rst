.. _devpi_um_packages_chapter:

Uploading, testing and pushing packages
=======================================

.. include:: ../links.rst

.. sidebar:: Summary
    
    This chapter ilustrates how to :term:`upload`, test and :term:`push` a package 
    between indexes or to an external index server such as https://pypi.python.org.

    *related commands*:
      * :ref:`cmdref_upload`
      * :ref:`cmdref_push` 
      * :ref:`cmdref_test`
      * :ref:`cmdref_install`

Overview
--------

As explained in the :ref:`label_userman_concepts_chapter` chapter, the **/root/pypi** is 
a special cache to http://pypi.python.org. 

Using the indexes created in the :ref:`previous chapter <devpi_um_indices_chapter>`, we
will show how to:

   * to install a package from ``PyPI`` 
     (:ref:`jump to <devpi_um_packages_pypi_install>`)
     
   * :term:`upload` a :term:`release file` to an index (``dev``) 
     (:ref:`jump to <devpi_um_packages_rf_upload>`)
     
   * :term:`upload` :term:`release files <release file>` from a directory 
     (:ref:`jump to <devpi_um_packages_fromdir_upload>`)
     
   * :term:`push` that :term:`release file` to an ``upstream`` index (``prod``) 
     (:ref:`jump to <devpi_um_packages_push>`)
     
   * access the :term:`release file` from another user index 
     (:ref:`jump to <devpi_um_packages_share>`)
     
   * deal with shadowed :term:`release files <release file>`  
     (:ref:`jump to <devpi_um_packages_shadow>`)
     
   * :term:`upload` documentation to the devpi server 
     (:ref:`jump to <devpi_um_packages_test>`)
     
   * test and upload test results to the devpi server 
     (:ref:`jump to <devpi_um_packages_doc>`)

For this purpose will use a sample packahe which has the following structure:

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


   
.. _devpi_um_packages_pypi_install:
   
Installing from PyPI
--------------------

While this topic has been mentioned in many parts of the documentation, we would like 
to reiterate that the `devpi`_ server acts as a http://pypi.python.org cache::

   $ devpi install jsontree
   --> $ /home/lpbrac/bitbucket/devpi_doc_contrib_1_0/bin/pip install --pre -U -i http://localhost:3141/emilie/dev/+simple/ jsontree
   Requirement already up-to-date: jsontree in /home/lpbrac/bitbucket/devpi_doc_contrib_1_0/lib/python2.7/site-packages
   Cleaning up...
   
From there::

   $ pwd 
   /home/lpbrac/bitbucket/devpi_doc_contrib_1_0/doc/userman

.. _devpi_um_packages_rf_upload:

Uploading a Release File
------------------------

Uploading the sample release file can be done as follow (default format is sdist)::

   $ cd pysober; devpi upload 
   created workdir /tmp/devpi8
   --> $ hg st -nmac .
   hg-exported project to <Exported /tmp/devpi8/upload/pysober>
   --> $ /home/lpbrac/bitbucket/devpi_doc_contrib_1_0/bin/python /home/lpbrac/bitbucket/devpi_doc_contrib_1_0/local/lib/python2.7/site-packages/devpi/upload/setuppy.py /tmp/devpi8/upload/pysober http://localhost:3141/emilie/dev/ emilie emilie-c8986532a974df40a7072fe39ef9d6506c28951b89bf3721dfafa37fe403801e.BPA3oQ.oOOevxyMd1KaAr1KAkufxvlm4lo register -r devpi
   warning: check: missing required meta-data: url
   
   release registered to http://localhost:3141/emilie/dev/
   --> $ /home/lpbrac/bitbucket/devpi_doc_contrib_1_0/bin/python /home/lpbrac/bitbucket/devpi_doc_contrib_1_0/local/lib/python2.7/site-packages/devpi/upload/setuppy.py /tmp/devpi8/upload/pysober http://localhost:3141/emilie/dev/ emilie emilie-c8986532a974df40a7072fe39ef9d6506c28951b89bf3721dfafa37fe403801e.BPA3oQ.oOOevxyMd1KaAr1KAkufxvlm4lo sdist --formats gztar upload -r devpi
   warning: sdist: standard file not found: should have one of README, README.txt
   
   warning: check: missing required meta-data: url
   
   submitted dist/pysober-0.1.0.tar.gz to http://localhost:3141/emilie/dev/
   
We can then verify that the project has been uploaded::

   $ devpi list pysober
   list result: http://localhost:3141/emilie/dev/
   emilie/dev/pysober/0.1.0/pysober-0.1.0.tar.gz
   
Assuming that we create a new version::

   $ sed -i 's/^\s*__version__.*/__version__ = "0.2.0"/g' pysober/pysober.py
   
We can now upload the new version::

   $ cd pysober; devpi upload
   created workdir /tmp/devpi9
   --> $ hg st -nmac .
   hg-exported project to <Exported /tmp/devpi9/upload/pysober>
   --> $ /home/lpbrac/bitbucket/devpi_doc_contrib_1_0/bin/python /home/lpbrac/bitbucket/devpi_doc_contrib_1_0/local/lib/python2.7/site-packages/devpi/upload/setuppy.py /tmp/devpi9/upload/pysober http://localhost:3141/emilie/dev/ emilie emilie-c8986532a974df40a7072fe39ef9d6506c28951b89bf3721dfafa37fe403801e.BPA3oQ.oOOevxyMd1KaAr1KAkufxvlm4lo register -r devpi
   warning: check: missing required meta-data: url
   
   release registered to http://localhost:3141/emilie/dev/
   --> $ /home/lpbrac/bitbucket/devpi_doc_contrib_1_0/bin/python /home/lpbrac/bitbucket/devpi_doc_contrib_1_0/local/lib/python2.7/site-packages/devpi/upload/setuppy.py /tmp/devpi9/upload/pysober http://localhost:3141/emilie/dev/ emilie emilie-c8986532a974df40a7072fe39ef9d6506c28951b89bf3721dfafa37fe403801e.BPA3oQ.oOOevxyMd1KaAr1KAkufxvlm4lo sdist --formats gztar upload -r devpi
   warning: sdist: standard file not found: should have one of README, README.txt
   
   warning: check: missing required meta-data: url
   
   submitted dist/pysober-0.2.0.tar.gz to http://localhost:3141/emilie/dev/

.. _devpi_um_packages_fromdir_upload:

Uploading from a Directory
--------------------------

``To be documented``

.. _devpi_um_packages_push:

Push a Release File (to Another Index)
--------------------------------------

``To be documented``

.. _devpi_um_packages_share:

Sharing Release Files
---------------------

``To be documented``

.. _devpi_um_packages_shadow:

Shadowed Release Files
----------------------

``To be documented``

.. _devpi_um_packages_doc:

Uploading Documentation
-----------------------

``To be documented``

.. _devpi_um_packages_test:

Testing
-------

``To be documented``

.. _devpi_um_packages_results:

Uploading Test Results
----------------------

``To be documented``







   
   



