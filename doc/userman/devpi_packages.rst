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

   * :term:`remove` a :term:`release file` or project from an index
     (:ref:`jump to <devpi_um_packages_rf_remove>`)
     
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
   --> $ /home/hpk/venv/0/bin/pip install -U -i http://localhost:3141/emilie/dev/+simple/ jsontree  [PIP_USE_WHEEL=1,PIP_PRE=1]
   http://localhost:3141/emilie/dev/+simple/jsontree/ uses an insecure transport scheme (http). Consider using https if localhost:3141 has it available
   Requirement already up-to-date: jsontree in /home/hpk/venv/0/lib/python2.7/site-packages
   Cleaning up...
   
From there::

   $ pwd 
   /home/hpk/p/devpi/doc/userman

.. _devpi_um_packages_rf_upload:

Uploading a Release File
------------------------

Uploading the sample release file can be done as follow (default format is sdist)::

   $ cd pysober; devpi upload 
   using workdir /tmp/devpi6
   --> $ /usr/bin/hg st -nmac . 
   hg-exported project to /tmp/devpi6/upload/pysober -> new CWD
   --> $ /home/hpk/venv/0/bin/python setup.py sdist --formats gztar 
   built: /home/hpk/p/devpi/doc/userman/pysober/dist/pysober-0.1.0.tar.gz [SDIST.TGZ] 2kb
   register pysober-0.1.0 to http://localhost:3141/emilie/dev/
   file_upload of pysober-0.1.0.tar.gz to http://localhost:3141/emilie/dev/

.. note::

       The ``upload`` command effectively calls ``python setup.py register``
       and ``python setup.py sdist upload`` using a wrapper script that
       makes sure we are doing these operations against our current
       in-use index.
   
Let's verify that the project has been uploaded::

   $ devpi list pysober
   http://localhost:3141/emilie/dev/+f/dcc/303d3f9ed7f0c/pysober-0.1.0.tar.gz
   
Assuming that we create a new version::

   $ sed -i 's/^\s*__version__.*/__version__ = "0.2.0"/g' pysober/pysober.py
   
We can now upload the new version::

   $ cd pysober; devpi upload
   using workdir /tmp/devpi7
   --> $ /usr/bin/hg st -nmac . 
   hg-exported project to /tmp/devpi7/upload/pysober -> new CWD
   pre-build: cleaning /home/hpk/p/devpi/doc/userman/pysober/dist
   --> $ /home/hpk/venv/0/bin/python setup.py sdist --formats gztar 
   built: /home/hpk/p/devpi/doc/userman/pysober/dist/pysober-0.2.0.tar.gz [SDIST.TGZ] 2kb
   register pysober-0.2.0 to http://localhost:3141/emilie/dev/
   file_upload of pysober-0.2.0.tar.gz to http://localhost:3141/emilie/dev/
   
We can verify that we uploaded two versions of our release file::

   $ devpi list pysober
   http://localhost:3141/emilie/dev/+f/061/be263fde59d40/pysober-0.2.0.tar.gz
   http://localhost:3141/emilie/dev/+f/dcc/303d3f9ed7f0c/pysober-0.1.0.tar.gz
   
.. _devpi_um_packages_rf_remove: 

Removing A Release File (or project)
------------------------------------

.. note:: The following only work from :term:`volatile` indexes. This is a safeguard
          to prevent deleting production indexes. 
   
If the :term:`release file` version 0.0.2 was uploaded by error, it can easily be 
removed::

   $ devpi remove -y pysober==0.2.0
   About to remove the following releases and distributions
   version: 0.2.0
     - http://localhost:3141/emilie/dev/+f/061/be263fde59d40/pysober-0.2.0.tar.gz
   Are you sure (yes/no)? yes (autoset from -y option)
   deleting release 0.2.0 of pysober
   
.. regendoc bug
   
::

   $ devpi list pysober   
   http://localhost:3141/emilie/dev/+f/dcc/303d3f9ed7f0c/pysober-0.1.0.tar.gz
   
In the event the entire project was wrongly created, it is also possible to 
delete it (beware, this can't be undone)::

   $ devpi remove -y pysober
   About to remove the following releases and distributions
   version: 0.1.0
     - http://localhost:3141/emilie/dev/+f/dcc/303d3f9ed7f0c/pysober-0.1.0.tar.gz
   Are you sure (yes/no)? yes (autoset from -y option)
   deleting release 0.1.0 of pysober
   
.. regendoc bug
   
And has the list command show, the project is no longer there::

   $ devpi list pysober   
   GET http://localhost:3141/emilie/dev/pysober/
   404 Not Found: project u'pysober' does not exist

.. _devpi_um_packages_fromdir_upload:

Uploading from a Directory
--------------------------

In the :ref:`previous section <devpi_um_packages_rf_remove>` we delete the project ``pysober``.  Let's execute a direct packaging step and then upload
the resulting release file.  First the typical ``setup.py`` packaging call::

   $ cd pysober ; python setup.py sdist
   running sdist
   running egg_info
   writing pysober.egg-info/PKG-INFO
   writing top-level names to pysober.egg-info/top_level.txt
   writing dependency_links to pysober.egg-info/dependency_links.txt
   reading manifest file 'pysober.egg-info/SOURCES.txt'
   reading manifest template 'MANIFEST.in'
   writing manifest file 'pysober.egg-info/SOURCES.txt'
   running check
   creating pysober-0.2.0
   creating pysober-0.2.0/doc
   creating pysober-0.2.0/doc/source
   creating pysober-0.2.0/pysober.egg-info
   creating pysober-0.2.0/test
   making hard links in pysober-0.2.0...
   hard linking MANIFEST.in -> pysober-0.2.0
   hard linking README -> pysober-0.2.0
   hard linking pysober.py -> pysober-0.2.0
   hard linking setup.py -> pysober-0.2.0
   hard linking tox.ini -> pysober-0.2.0
   hard linking doc/Makefile -> pysober-0.2.0/doc
   hard linking doc/source/conf.py -> pysober-0.2.0/doc/source
   hard linking doc/source/index.rst -> pysober-0.2.0/doc/source
   hard linking doc/source/overview.rst -> pysober-0.2.0/doc/source
   hard linking pysober.egg-info/PKG-INFO -> pysober-0.2.0/pysober.egg-info
   hard linking pysober.egg-info/SOURCES.txt -> pysober-0.2.0/pysober.egg-info
   hard linking pysober.egg-info/dependency_links.txt -> pysober-0.2.0/pysober.egg-info
   hard linking pysober.egg-info/not-zip-safe -> pysober-0.2.0/pysober.egg-info
   hard linking pysober.egg-info/top_level.txt -> pysober-0.2.0/pysober.egg-info
   hard linking test/conftest.py -> pysober-0.2.0/test
   hard linking test/test_pysober.py -> pysober-0.2.0/test
   Writing pysober-0.2.0/setup.cfg
   Creating tar archive
   removing 'pysober-0.2.0' (and everything under it)

We now have a release file in the ``dist`` directory::

   $ ls pysober/dist
   pysober-0.2.0.tar.gz

`devpi`_ provides a way to upload all the :term:`release files <release file>` 
from a directory::

   $ devpi upload --from-dir pysober/dist
   register pysober-0.2.0 to http://localhost:3141/emilie/dev/
   file_upload of pysober-0.2.0.tar.gz to http://localhost:3141/emilie/dev/
   
which in our case would restore the project::

   $ devpi list pysober   
   http://localhost:3141/emilie/dev/+f/4c7/2b661a630b626/pysober-0.2.0.tar.gz

You can use the ``--only-latest`` option if you have multiple 
:term:`release file` files with different versions, causing
the upload of only the respective latest version.

.. _devpi_um_packages_push:

Push a Release File (to Another Index)
--------------------------------------

When an index has bases other that ``/root/pypi``, it is possible (provided the
user is in the ``acl_upload`` list) to :term:`push` a package to one of those
bases (index).

In this example, the current index is ``/emilie/dev/`` and we want to  :term:`push` 
version ``0.2.0`` to ``/emilie/prod``::

   $ devpi push  pysober-0.2.0 emilie/prod
      200 register pysober 0.2.0 -> emilie/prod
      200 store_releasefile emilie/prod/+f/4c7/2b661a630b626/pysober-0.2.0.tar.gz
   
When listing the index we see that the same :term:`release file` is listed
twice, once in ``/emilie/dev`` and once in ``/emilie/prod``. Basically, 
the :term:`release file` in ``/emilie/prod`` is shadowed by the one (same)
in ``/emilie/dev`` (more on this in :ref:``devpi_um_packages_shadow``)::

   $ devpi list    
   pysober

.. _devpi_um_packages_share:

Sharing Release Files
---------------------

As explained in the :ref:`devpi_um_indices_modify` section, it is possible to 
modify the base of a given index to share :term:`release files <release file>`  
between indexes or users.

Let's login as Sophie::

   $ devpi login sophie --password=1234
   logged in 'sophie', credentials valid for 10.00 hours

Let's also make sure we now switch (use) the appropriate index::

   $ devpi use /sophie/dev    
   current devpi index: http://localhost:3141/sophie/dev (logged in as sophie)
   ~/.pydistutils.cfg     : no config file exists
   ~/.pip/pip.conf        : no config file exists
   ~/.buildout/default.cfg: no config file exists
   always-set-cfg: no
   
Finally let's take a look at the index to see if the ``pysober`` is present::

   $ devpi list pysober
   GET http://localhost:3141/sophie/dev/pysober/
   404 Not Found: project u'pysober' does not exist

As expected, this package is not found. In order to access this package, Sophie 
can modify her ``dev`` index to use ``/emilie/prod`` index as a base::

   $ devpi index /sophie/dev bases=/emilie/prod,/sophie/prod  
   /sophie/dev changing bases: ['/emilie/prod', '/sophie/prod']
   http://localhost:3141/sophie/dev:
     type=stage
     bases=emilie/prod,sophie/prod
     volatile=True
     uploadtrigger_jenkins=None
     acl_upload=sophie
     pypi_whitelist=
   
The list command now gives her a different picture::

   $ devpi list pysober
   http://localhost:3141/emilie/prod/+f/4c7/2b661a630b626/pysober-0.2.0.tar.gz
   
However, keep in mind that the :term:`release file` is not copied to Sophie's
``dev`` index but only made available through inheritance. Removing ``/emilie/prod``
as a base would further stop access to that file. 

While Sophie can install the package, she can not remove it::

   $ devpi remove -y pysober==0.2.0
   not deleting anything
   
She can however, modify the package::

   $ sed -i 's/^\s*__version__.*/__version__ = "0.2.1"/g' pysober/pysober.py
   
And upload a new version to her ``/sophie/dev`` index::

   $ cd pysober; devpi upload
   using workdir /tmp/devpi8
   --> $ /usr/bin/hg st -nmac . 
   hg-exported project to /tmp/devpi8/upload/pysober -> new CWD
   pre-build: cleaning /home/hpk/p/devpi/doc/userman/pysober/dist
   --> $ /home/hpk/venv/0/bin/python setup.py sdist --formats gztar 
   built: /home/hpk/p/devpi/doc/userman/pysober/dist/pysober-0.2.1.tar.gz [SDIST.TGZ] 2kb
   register pysober-0.2.1 to http://localhost:3141/sophie/dev/
   file_upload of pysober-0.2.1.tar.gz to http://localhost:3141/sophie/dev/
   
which leads to::

   $ devpi list pysober
   http://localhost:3141/sophie/dev/+f/49f/0ddfac40af6a2/pysober-0.2.1.tar.gz
   http://localhost:3141/emilie/prod/+f/4c7/2b661a630b626/pysober-0.2.0.tar.gz
   
Attempting to :term:`push` this :term:`release file` to Emilie's prod index would 
fails unless Emilie added Sophie in the ``acl_upload`` list::

   $ devpi push  pysober-0.2.1 emilie/prod
   PUSH http://localhost:3141/sophie/dev
   401 Unauthorized: user u'sophie' cannot upload to u'emilie/prod'
   
Sophie could however :term:`push` (from Emilie's ``prod`` index) the ``0.2.0`` 
version to her ``/sophie/dev`` index by first using the index::

   $ devpi use /emilie/prod   
   current devpi index: http://localhost:3141/emilie/prod (logged in as sophie)
   ~/.pydistutils.cfg     : no config file exists
   ~/.pip/pip.conf        : no config file exists
   ~/.buildout/default.cfg: no config file exists
   always-set-cfg: no

And then performing the :term:`push`::

   $ devpi push  pysober-0.2.0 sophie/dev
      200 register pysober 0.2.0 -> sophie/dev
      200 store_releasefile sophie/dev/+f/4c7/2b661a630b626/pysober-0.2.0.tar.gz

Then switching back to her index::

   $ devpi use /sophie/dev
   current devpi index: http://localhost:3141/sophie/dev (logged in as sophie)
   ~/.pydistutils.cfg     : no config file exists
   ~/.pip/pip.conf        : no config file exists
   ~/.buildout/default.cfg: no config file exists
   always-set-cfg: no

Sophie would see the following::

   $ devpi list pysober
   http://localhost:3141/sophie/dev/+f/49f/0ddfac40af6a2/pysober-0.2.1.tar.gz
   http://localhost:3141/sophie/dev/+f/4c7/2b661a630b626/pysober-0.2.0.tar.gz
   http://localhost:3141/emilie/prod/+f/4c7/2b661a630b626/pysober-0.2.0.tar.gz

.. note:: Now ``/emilie/prod/pysober-0.2.0 is now shadowed by the file 
          in the ``/dev`` index. Sophie could now reset her base and move 
          on with her own copy.

Contrary to the first failed attempt attempt to delete the ``0.2.0`` version , 
the subsequent attempt would work::

   $ devpi remove -y pysober==0.2.0
   About to remove the following releases and distributions
   version: 0.2.0
     - http://localhost:3141/sophie/dev/+f/4c7/2b661a630b626/pysober-0.2.0.tar.gz
   Are you sure (yes/no)? yes (autoset from -y option)
   deleting release 0.2.0 of pysober
   
Leaving now her index in that state::

   $ devpi list pysober
   http://localhost:3141/sophie/dev/+f/49f/0ddfac40af6a2/pysober-0.2.1.tar.gz
   http://localhost:3141/emilie/prod/+f/4c7/2b661a630b626/pysober-0.2.0.tar.gz

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







   
   



