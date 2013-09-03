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
   created workdir /tmp/devpi39
   --> $ hg st -nmac .
   hg-exported project to <Exported /tmp/devpi39/upload/pysober>
   --> $ /home/lpbrac/bitbucket/devpi_doc_contrib_1_0/bin/python /home/lpbrac/bitbucket/devpi_doc_contrib_1_0/local/lib/python2.7/site-packages/devpi/upload/setuppy.py /tmp/devpi39/upload/pysober http://localhost:3141/emilie/dev/ emilie emilie-e46158400e23cdef8bd7b1c1460299d50f32a64992d878d973f854b2f32eef1d.BPBapQ.9J9ptibFGGGR6P4c-uXUFivHR9c register -r devpi
   release registered to http://localhost:3141/emilie/dev/
   --> $ /home/lpbrac/bitbucket/devpi_doc_contrib_1_0/bin/python /home/lpbrac/bitbucket/devpi_doc_contrib_1_0/local/lib/python2.7/site-packages/devpi/upload/setuppy.py /tmp/devpi39/upload/pysober http://localhost:3141/emilie/dev/ emilie emilie-e46158400e23cdef8bd7b1c1460299d50f32a64992d878d973f854b2f32eef1d.BPBapQ.9J9ptibFGGGR6P4c-uXUFivHR9c sdist --formats gztar upload -r devpi
   submitted dist/pysober-0.1.0.tar.gz to http://localhost:3141/emilie/dev/
   
which is equivalent to::

   $ cd pysober; python setup.py sdit
   usage: setup.py [global_opts] cmd1 [cmd1_opts] [cmd2 [cmd2_opts] ...]
      or: setup.py --help [cmd1 cmd2 ...]
      or: setup.py --help-commands
      or: setup.py cmd --help
   
   error: invalid command 'sdit'
   
We can then verify that the project has been uploaded::

   $ devpi list pysober
   list result: http://localhost:3141/emilie/dev/
   emilie/dev/pysober/0.1.0/pysober-0.1.0.tar.gz
   
Assuming that we create a new version::

   $ sed -i 's/^\s*__version__.*/__version__ = "0.2.0"/g' pysober/pysober.py
   
We can now upload the new version::

   $ cd pysober; devpi upload
   created workdir /tmp/devpi40
   --> $ hg st -nmac .
   hg-exported project to <Exported /tmp/devpi40/upload/pysober>
   --> $ /home/lpbrac/bitbucket/devpi_doc_contrib_1_0/bin/python /home/lpbrac/bitbucket/devpi_doc_contrib_1_0/local/lib/python2.7/site-packages/devpi/upload/setuppy.py /tmp/devpi40/upload/pysober http://localhost:3141/emilie/dev/ emilie emilie-e46158400e23cdef8bd7b1c1460299d50f32a64992d878d973f854b2f32eef1d.BPBapQ.9J9ptibFGGGR6P4c-uXUFivHR9c register -r devpi
   release registered to http://localhost:3141/emilie/dev/
   --> $ /home/lpbrac/bitbucket/devpi_doc_contrib_1_0/bin/python /home/lpbrac/bitbucket/devpi_doc_contrib_1_0/local/lib/python2.7/site-packages/devpi/upload/setuppy.py /tmp/devpi40/upload/pysober http://localhost:3141/emilie/dev/ emilie emilie-e46158400e23cdef8bd7b1c1460299d50f32a64992d878d973f854b2f32eef1d.BPBapQ.9J9ptibFGGGR6P4c-uXUFivHR9c sdist --formats gztar upload -r devpi
   submitted dist/pysober-0.2.0.tar.gz to http://localhost:3141/emilie/dev/
   
again equivalent to::

   $ cd pysober; python setup.py sdit
   usage: setup.py [global_opts] cmd1 [cmd1_opts] [cmd2 [cmd2_opts] ...]
      or: setup.py --help [cmd1 cmd2 ...]
      or: setup.py --help-commands
      or: setup.py cmd --help
   
   error: invalid command 'sdit'
   
And we now have::

   $ devpi list pysober
   list result: http://localhost:3141/emilie/dev/
   emilie/dev/pysober/0.2.0/pysober-0.2.0.tar.gz
   emilie/dev/pysober/0.1.0/pysober-0.1.0.tar.gz
   
.. _devpi_um_packages_rf_remove: 

Removing A Release File (or project)
------------------------------------

.. note:: The following only work from :term:`volatile` indexes. This is a safeguard
          to prevent deleting production indexes. 
   
If the :term:`release file` version 0.0.2 was uploaded by error, it can easily be 
removed::

   $ devpi remove -y pysober-0.2.0
   About to remove the following release files and metadata:
      emilie/dev/pysober/0.2.0/pysober-0.2.0.tar.gz
   Are you sure (yes/no)? yes (autoset from -y option)
   
.. regendoc bug
   
::

   $ devpi list pysober   
   list result: http://localhost:3141/emilie/dev/
   emilie/dev/pysober/0.1.0/pysober-0.1.0.tar.gz
   
In the event the entire project was wrongly created, it is also possible to 
delete it (beware, this can't be undone)::

   $ devpi remove -y pysober
   About to remove the following release files and metadata:
      emilie/dev/pysober/0.1.0/pysober-0.1.0.tar.gz
   Are you sure (yes/no)? yes (autoset from -y option)
   
.. regendoc bug
   
And has the list command show, the project is no longer there::

   $ devpi list pysober   
   list result: http://localhost:3141/emilie/dev/

.. _devpi_um_packages_fromdir_upload:

Uploading from a Directory
--------------------------

In the :ref:`previous section <devpi_um_packages_rf_remove>` we delete the project ``pysober``.
However the files are still in the local file system ``dist`` folder::

   $ ls pysober/dist
   pysober-0.2.0.tar.gz

`devpi`_ provide a way to upload all the :term:`release files <release file>` 
from a directory::

   $ devpi upload --from-dir pysober/dist
   pysober-0.2.0 registered to http://localhost:3141/emilie/dev/
   pysober-0.2.0.tar.gz posted to http://localhost:3141/emilie/dev/
   
which in our case would restore the project::

   $ devpi list pysober   
   list result: http://localhost:3141/emilie/dev/
   emilie/dev/pysober/0.2.0/pysober-0.2.0.tar.gz

When using the ``--only-latest``, only the most recent :term:`release file` is
uploaded, on this case ``pysober-0.2.0``   

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
   200 store_releasefile pysober-0.2.0.tar.gz -> emilie/prod
   
When listing the index we see that the same :term:`release file` is listed
twice, once in ``/emilie/dev`` and once in ``/emilie/prod``. Basically, 
the :term:`release file` in ``/emilie/prod`` is shadowed by the one (same)
in ``/emilie/dev`` (more on this in :ref:``devpi_um_packages_shadow``)::

   $ devpi list    
   list result: http://localhost:3141/emilie/dev/
   pysober

.. _devpi_um_packages_share:

Sharing Release Files
---------------------

As explained in the :ref:`devpi_um_indices_modify` section, it is possible to 
modify the base of a given index to share :term:`release files <release file>: 
between indexes or users.

Let's login as Sophie::

   $ devpi login sophie --password=1234
   logged in 'sophie', credentials valid for 10.00 hours

Let's also make sure we now switch (use) the appropriate index::

   $ devpi use /sophie/dev    
   using index: http://localhost:3141/sophie/dev/ (logged in as sophie)
   
Finally let's take a look at the index to see if the ``pysober`` is present::

   $ devpi list pysober
   list result: http://localhost:3141/sophie/dev/

As expected, this package is not found. In order to access this package, Sophie 
can modify her ``dev`` index to use ``/emilie/prod`` index as a base::

   $ devpi index /sophie/dev bases=/emilie/prod,/sophie/prod  
   /sophie/dev changing bases: /emilie/prod,/sophie/prod
   /sophie/dev:
     type=stage
     bases=emilie/prod,sophie/prod
     volatile=True
     uploadtrigger_jenkins=None
     acl_upload=sophie
   
The list command now gives her a different picture::

   $ devpi list pysober
   list result: http://localhost:3141/sophie/dev/
   emilie/prod/pysober/0.2.0/pysober-0.2.0.tar.gz
   
However, keep in mind that the :term:`release file` is not copied to Sophie's
``dev`` index but only made available through inheritance. Removing ``/emilie/prod``
as a base would further stop access to that file. 

While Sophie can install the package, she can not remove it::

   $ devpi remove -y pysober-0.2.0
   nothing to delete
   
She can however, modify the package::

   $ sed -i 's/^\s*__version__.*/__version__ = "0.2.1"/g' pysober/pysober.py
   
And upload a new version to her ``/sophie/dev`` index::

   $ cd pysober; devpi upload
   created workdir /tmp/devpi41
   --> $ hg st -nmac .
   hg-exported project to <Exported /tmp/devpi41/upload/pysober>
   --> $ /home/lpbrac/bitbucket/devpi_doc_contrib_1_0/bin/python /home/lpbrac/bitbucket/devpi_doc_contrib_1_0/local/lib/python2.7/site-packages/devpi/upload/setuppy.py /tmp/devpi41/upload/pysober http://localhost:3141/sophie/dev/ sophie sophie-efb9aedb069ee33192e50db173f68940dbffb341dbc134e7fb6641a190e8bb8f.BPBaqw.8GZZnKnWS3xWNUCB-zl6wOz9hCg register -r devpi
   release registered to http://localhost:3141/sophie/dev/
   --> $ /home/lpbrac/bitbucket/devpi_doc_contrib_1_0/bin/python /home/lpbrac/bitbucket/devpi_doc_contrib_1_0/local/lib/python2.7/site-packages/devpi/upload/setuppy.py /tmp/devpi41/upload/pysober http://localhost:3141/sophie/dev/ sophie sophie-efb9aedb069ee33192e50db173f68940dbffb341dbc134e7fb6641a190e8bb8f.BPBaqw.8GZZnKnWS3xWNUCB-zl6wOz9hCg sdist --formats gztar upload -r devpi
   submitted dist/pysober-0.2.1.tar.gz to http://localhost:3141/sophie/dev/
   
which leads to::

   $ devpi list pysober
   list result: http://localhost:3141/sophie/dev/
   sophie/dev/pysober/0.2.1/pysober-0.2.1.tar.gz
   emilie/prod/pysober/0.2.0/pysober-0.2.0.tar.gz
   
Attempting to :term:`push` this :term:`release file` to Emilie's prod index would 
fails unless Emilie added Sophie in the ``acl_upload`` list::

   $ devpi push  pysober-0.2.1 emilie/prod
   removed expired authentication information
   PUSH http://localhost:3141/sophie/dev/
   401 Unauthorized: user u'sophie' cannot upload to u'emilie/prod'
   
Sophie could however :term:`push` (from Emilie's ``prod`` index) the ``0.2.0`` 
version to her ``/sophie/dev`` index by first using the index::

   $ devpi use /emilie/prod   
   using index: http://localhost:3141/emilie/prod/ (not logged in)

And then performing the :term:`push`::

   $ devpi push  pysober-0.2.0 sophie/dev
   PUSH http://localhost:3141/emilie/prod/
   401 Unauthorized: user None cannot upload to u'sophie/dev'

Then switching back to her index::

   $ devpi use /sophie/dev
   using index: http://localhost:3141/sophie/dev/ (not logged in)
Sophie would see the following::

   $ devpi list pysober
   list result: http://localhost:3141/sophie/dev/
   sophie/dev/pysober/0.2.1/pysober-0.2.1.tar.gz
   emilie/prod/pysober/0.2.0/pysober-0.2.0.tar.gz

.. note:: Now ``/emilie/prod/pysober-0.2.0 is now shadowed by the file 
          in the ``/dev`` index. Sophie could now reset her base and move 
          on with her own copy.

Contrary to the first failed attempt attempt to delete the ``0.2.0`` version , 
the subsequent attempt would work::

   $ devpi remove -y pysober-0.2.0
   nothing to delete
   
Leaving now her index in that state::

   $ devpi list pysober
   list result: http://localhost:3141/sophie/dev/
   sophie/dev/pysober/0.2.1/pysober-0.2.1.tar.gz
   emilie/prod/pysober/0.2.0/pysober-0.2.0.tar.gz

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







   
   



