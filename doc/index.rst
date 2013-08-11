devpi: pypi caching server and one-stop tool for python packaging
=================================================================

.. include:: links.rst

The devpi project features a powerful PyPI server and a command line
tool to help with release, testing and installation activities.  For
your convenience and single laptop usage, the devpi_ meta package pulls
in both the server and client packages:

- ``devpi-server``: well-tested and easy-to-use pypi server with
  some :doc:`unique features <features-server>`, among them a self-updating
  pypi.python.org cache and private overlay indexes (merging in all packages
  from parent indexes).

- ``devpi-client``: one-stop ``devpi`` tool with sub commands for
  uploading, testing and push-to-pypi operations as well as managing 
  users and github-style user/INDEX overlay indexes.

If you aim for single-laptop usage and quickly trying things out, read on below.  
If you aim for a company wide setup, checkout :doc:`quickstart-server`.

For step by step introduction to devpi, please refer to the :ref:`userman_index`
For integration and triggering of Jenkins jobs from devpi, see :doc:`jenkins`.

**Compatibility: Windows/Python2.7, Linux/Python2.6,2.7, OSX/Python2.6/2.7**

.. _label_quickstart_section:

Quickstart: install, upload, test, push
---------------------------------------

Installing devpi client and server
++++++++++++++++++++++++++++++++++

::

	pip install devpi

This will install ``devpi-client`` and ``devpi-server`` pypi packages.

.. _`devpicommands`:

devpi install: installing a package
+++++++++++++++++++++++++++++++++++

We can now use the ``devpi`` command line client to ``pip install``
a pypi package (here ``pytest`` as an example) through an
auto-started caching devpi-server::

    $ devpi install --venv=v1 pytest
    automatically starting devpi-server for http://localhost:3141
    *** logfile is at
    --> $ virtualenv -q v1
    --> $ v1/bin/pip install --pre -U -i http://localhost:3141/root/dev/+simple/ pytest
    Downloading/unpacking pytest
      Running setup.py egg_info for package pytest
        
    Downloading/unpacking py>=1.4.13dev6 (from pytest)
      Running setup.py egg_info for package py
        
    Installing collected packages: pytest, py
      Running setup.py install for pytest
        
        Installing py.test script to /home/hpk/p/devpi/doc/v1/bin
        Installing py.test-2.7 script to /home/hpk/p/devpi/doc/v1/bin
      Running setup.py install for py
        
    Successfully installed pytest py
    Cleaning up...

Here is what happened:

- ``devpi-server`` was automatically started because we are
  using the default ``localhost:3141`` url and no server responded there.

- a virtualenv ``v1`` was created because it didn't exist

- ``pip install`` was configured to use the default devpi ``root/dev`` 
  index which is an index which inherits pypi.python.org packages.

Let's check that ``pytest`` was installed correctly::

    $ v1/bin/py.test --version
    This is py.test version 2.3.5, imported from /home/hpk/p/devpi/doc/v1/local/lib/python2.7/site-packages/pytest.pyc

You may invoke the ``devpi install`` command a second time which goes
much faster and works offline.

devpi upload: uploading one or more packages
++++++++++++++++++++++++++++++++++++++++++++

In order to upload packages to the ``root/dev`` index you need to login::

    $ devpi login root --password ""
    logged in 'root', credentials valid for 10.00 hours

Let's verify we are logged in to the correct default ``root/dev`` index::

    $ devpi use
    using index: http://localhost:3141/root/dev/ (logged in as root)
    no current install venv set

Now go to the directory of a ``setup.py`` file of one of your projects  
(we assume it is named ``example``) to build and upload your package
to the local ``root/dev`` default index::

    example $ devpi upload
    created workdir /tmp/devpi1103
    --> $ hg st -nmac .
    hg-exported project to <Exported /tmp/devpi1103/upload/example>
    --> $ /home/hpk/venv/0/bin/python /home/hpk/p/devpi/client/devpi/upload/setuppy.py /tmp/devpi1103/upload/example http://localhost:3141/root/dev/ root root-72509ca707b0f1f765548e62d9d849eb1a11768a240914a329b20a7eacbc8dda.BOmHsQ.AGHLxf9jG3dzHDSJALUZQ2wCLCY register -r devpi
    release registered to http://localhost:3141/root/dev/
    --> $ /home/hpk/venv/0/bin/python /home/hpk/p/devpi/client/devpi/upload/setuppy.py /tmp/devpi1103/upload/example http://localhost:3141/root/dev/ root root-72509ca707b0f1f765548e62d9d849eb1a11768a240914a329b20a7eacbc8dda.BOmHsQ.AGHLxf9jG3dzHDSJALUZQ2wCLCY sdist --formats gztar upload -r devpi
    submitted dist/example-1.0.tar.gz to http://localhost:3141/root/dev/

There are three triggered actions:

- detection of a mercurial repository, leading to copying all versioned
  files to a temporary work dir.  If you are not using mercurial,
  the copy-step is skipped and the upload operates directly on your source
  tree.

- registering the ``example`` release as defined in ``setup.py`` to 
  the ``root/dev`` index.

- building and uploading a ``gztar`` formatted release file to the
  ``root/dev`` index.

We can now install the freshly uploaded package::

    $ devpi install --venv=v1 example
    --> $ v1/bin/pip install --pre -U -i http://localhost:3141/root/dev/+simple/ example
    Downloading/unpacking example
      Downloading example-1.0.tar.gz
      Running setup.py egg_info for package example
        
    Installing collected packages: example
      Running setup.py install for example
        
    Successfully installed example
    Cleaning up...

This installed your just uploaded package from the default ``root/dev``
index.

.. note::

    ``devpi upload`` allows to simultanously upload multiple different 
    formats of your release files such as ``sdist.zip`` or ``bdist_egg``.
    The default is ``sdist.tgz``.

uploading sphinx docs
++++++++++++++++++++++++++++++++

If you have sphinx-based docs you can upload them as well::

    devpi upload --with-docs

This will build and upload sphinx-documentation by configuring and running
this command::

    setup.py build_sphinx -E --build-dir $BUILD_DIR \
             upload_docs --upload-dir $BUILD_DIR/html


uploading existing release files
++++++++++++++++++++++++++++++++

If you have a directory with existing package files::

    devpi upload --from-dir PATH/TO/DIR

will recursively collect all archives files, register
and upload them to our local ``root/dev`` pypi index.

listing or removing projects and release files
++++++++++++++++++++++++++++++++++++++++++++++

If you issue::

    devpi list

you get a list of all project names where release files are
registered on the current index.  You can restrict it to
a project or a particular version of a project::

    devpi list PROJECT
    devpi list PROJECT-1.0

will give you all release files for the given PROJECT or PROJECT-1.0,
respectively.  The ``remove`` subcommand uses the same syntax::

    devpi remove PROJECT
    devpi remove PROJECT-1.0

Unless you specify the ``-y`` option you will be asked to confirm
the list of release files that are to be deleted.

devpi test: testing an uploaded package
+++++++++++++++++++++++++++++++++++++++

If you have a package using tox_ you may invoke::

    devpi test PACKAGENAME  # package needs to contain tox.ini

this will download the latest release of ``PACKAGENAME`` and run tox
against it.  You can also try to run ``devpi test`` with any 3rd party 
pypi package.

devpi push: send a release to another index
+++++++++++++++++++++++++++++++++++++++++++

You can push a release with all release files and docs
to another devpi index::

    devpi push NAME-VERSION root/staging

This will determine all files belonging to the specified ``NAME-VERSION``
release and copy them to the ``root/staging`` index. 

You can upload a release with all release files and docs
to an external index listed in your ``.pypirc`` configuration file::

    devpi push NAME-VERSION pypi:pypi

this will push all release files for this version to
the external ``pypi`` index server, using credentials
and the URL found in the ``pypi`` section in your
``.pypirc``, typically pointing to https://pypi.python.org/pypi.

devpi use: show index and other info
++++++++++++++++++++++++++++++++++++

::

    $ devpi use
    using index: http://localhost:3141/root/dev/ (logged in as root)
    no current install venv set

In the default configuration we do not need credentials
and thus do not need to be logged in.


devpi server: controling the automatic server
+++++++++++++++++++++++++++++++++++++++++++++

Let's look at our current automatically started server::

    $ devpi server 
    automatic server is running with pid 29155

Let's stop it::

    $ devpi server --stop
    killed automatic server pid=29155

Note that with most ``devpi`` commands the server will be started
up again when needed.  As soon as you start ``devpi use`` with 
any other root url than ``http://localhost:3141`` no automatic 
server management takes place anymore.

See :doc:`quickstart-server` for more deployment options and how
to use ``devpi-server`` with plain ``pip``, ``easy_install`` or
``setup.py`` invocations.

.. toctree::
   :maxdepth: 2

   status
   quickstart-server
   features-server
   userman/index.rst
   jenkins
   curl

.. toctree::
   :hidden:

   links


Example timing
--------------

Here is a little screen session when using a fresh ``devpi-server``
instance, installing itself in a fresh virtualenv::

    hpk@teta:~/p/devpi-server$ virtualenv devpi >/dev/null
    hpk@teta:~/p/devpi-server$ source devpi/bin/activate
    (devpi) hpk@teta:~/p/devpi-server$ time pip install -q \
                -i https://pypi.python.org/simple/ django-treebeard

    real  15.871s
    user   3.884s
    system 2.684s

So that took around 15 seconds.  Now lets remove the virtualenv, recreate
it and install ``django-treebeard`` again, now using devpi-server::

    (devpi) hpk@teta:~/p/devpi-server$ rm -rf devpi
    (devpi) hpk@teta:~/p/devpi-server$ virtualenv devpi  >/dev/null
    (devpi)hpk@teta:~/p/devpi-server$ time pip install -q -i http://localhost:3141/root/pypi/+simple/ django-treebeard

    real   6.219s
    user   3.912s
    system 2.716s

So it's around 2-3 times faster on a 30Mbit internet connection.

Known limitations
-----------------

- ``devpi-server`` currently does not follow any FTP links.

Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`

