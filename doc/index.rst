devpi: pypi caching server and one-stop tool for python packaging
====================================================================

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

**Compatibility: Windows/Python2.7, Linux/Python2.6,2.7, OSX/Python2.6/2.7**

Quickstart: install, upload, test, push 
--------------------------------------------

Installing devpi client and server
++++++++++++++++++++++++++++++++++++++++

::

	pip install devpi

This will install ``devpi-client`` and ``devpi-server`` pypi packages.

.. _`devpicommands`:

devpi install: installing a package 
++++++++++++++++++++++++++++++++++++++++

We can now use the ``devpi`` command line client to ``pip install``
a pypi package (here ``pytest`` as an example) through an
auto-started caching devpi-server::

    $ devpi install --venv=v1 pytest
    automatically starting devpi-server at http://localhost:3141/
    --> $ virtualenv v1
    Using real prefix '/usr'
    New python executable in v1/bin/python
    Please make sure you remove any previous custom paths from your /home/hpk/.pydistutils.cfg file.
    Installing setuptools............done.
    Installing pip...............done.
    --> $ v1/bin/pip install -U --force-reinstall -i http://localhost:3141/root/dev/+simple/ pytest
    Downloading/unpacking pytest
      Running setup.py egg_info for package pytest
        
    Downloading/unpacking py>=1.4.13dev6 (from pytest)
      Running setup.py egg_info for package py
        
    Installing collected packages: pytest, py
      Running setup.py install for pytest
        
        Installing py.test script to /tmp/doc-exec-15/v1/bin
        Installing py.test-2.7 script to /tmp/doc-exec-15/v1/bin
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
    This is py.test version 2.3.5, imported from /tmp/doc-exec-15/v1/local/lib/python2.7/site-packages/pytest.pyc

You may invoke the ``devpi install`` command a second time which should
go much faster and also work offline.

devpi upload: uploading one or more packages
+++++++++++++++++++++++++++++++++++++++++++++++

Go to a ``setup.py`` based project of yours and issue::

	devpi upload   # need to be in a directory with setup.py

You can now install the just uploaded package::

	devpi install --venv=v1 NAME_OF_YOUR_PACKAGE

This installed your just uploaded package from the default ``root/dev``
index.

.. note::

    ``devpi upload`` allows to upload multiple different formats
    of your release files such as ``sdist.zip`` or ``bdist_egg``.
    With the ``--withdocs`` option, you will also upload documentation.
    The default is ``sdist.tgz``.

uploading existing release files
+++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

If you have a directory with existing package files::

    devpi upload --from-dir PATH/TO/DIR

will recursively collect all archives files, register
and upload them to our private ``root/dev`` pypi index.

listing or removing projects and release files
+++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

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
+++++++++++++++++++++++++++++++++++++++++++++++

If you have a package using tox_ you may invoke::

    devpi test PACKAGENAME  # package needs to contain tox.ini

this will download the latest release of ``PACKAGENAME`` and run tox
against it.  You can also try to run ``devpi test`` with any 3rd party 
pypi package.

devpi push: send a release to another index
++++++++++++++++++++++++++++++++++++++++++++++++++++

After you repeated your upload and test cycle you
may at some point decide that a package is ready
and push it to an external pypi server::

    devpi push NAME-VERSION pypi:pypi

this will push all release files for this version to
the external ``pypi`` index server, using credentials
and the URL found in the ``pypi`` section in your
``.pypirc``, typically pointing to https://pypi.python.org/pypi.

devpi use: show index and other info
++++++++++++++++++++++++++++++++++++++++++++++++

::

    $ devpi use
    using index:  http://localhost:3141/root/dev/
    no current install venv set
    logged in as: root

In the default configuration we do not need credentials
and thus do not need to be logged in.


devpi server: controling the automatic server 
+++++++++++++++++++++++++++++++++++++++++++++++

Let's look at our current automatically started server::

    $ devpi server --nolog  # don't show server log info
    automatic server is running with pid 7133

Let's stop it::

    $ devpi server --stop
    TERMINATED 'devpi-server', pid 7133 -- logfile /home/hpk/.devpi/client/.xproc/devpi-server/xprocess.log

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
   curl

.. toctree::
   :hidden:

   links


Example timing
----------------

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
------------------

- ``devpi-server`` currently does not follow any FTP links.

Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`

