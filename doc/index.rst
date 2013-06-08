devpi: pypi caching server and one-stop tool for python packaging
====================================================================

.. include:: links.rst

The **devpi** project aims to support a variety of company- and
user-specific Python Package release, testing and installation 
activities.  The project is partly funded by a contract of a larger
geo-distributed company with merlinux_ and Holger Krekel as the 
lead developer.  The project is bound to see more releases in 2013, 
see :ref:`projectstatus`.

The project provides two MIT-licensed Python packages:

- ``devpi-server``: well-tested and easy-to-use pypi server with
  :doc:`unique features <features-server>` not found in other implementations.
  This server can be used from standard ``setup.py upload``
  and ``pip/easy_install`` invocations.

- ``devpi-client``: one-stop ``devpi`` tool with sub commands for managing 
  users and github-style user/INDEX overlay indexes, and wrapping
  common upload/test/install activities.


Quickstart: serve, install and upload
----------------------------------------

Install both server and client::

	pip install devpi

Start a server in one window::
  
	devpi-server  # and leave it running in the window, open new one

Install an arbitrary package (here ``pytest``) into a new ``subenv``
virtualenv directory::

	$ devpi install --venv=v1 pytest

Here ``pip`` used the default devpi ``root/dev`` index which is an
:ref:`overlay index <overlayindex>`, which inherits all pypi.python.org
packages.

Check that ``pytest`` was installed correctly::

	$ subenv/bin/py.test --version

Locally upload a ``setup.py`` based package::

	$ devpi upload   # need to be in a directory with setup.py

and install the just uploaded package::

	devpi install --venv=v1 NAME_OF_YOUR_PACKAGE

This installed your package and potentially all pypi dependencies
through the default ``root/dev`` index, 

.. toctree::
   :maxdepth: 2

   quickstart-client
   quickstart-server
   features-server
   company
   curl
   contact

.. toctree::
   :hidden:

   links


.. _projectstatus:

Project status and further developments
----------------------------------------

As of June 2013, around 250 automated tests are passing on
python2.7 and python2.6 on Ubuntu 12.04 and Windows 7.

Both the ``devpi-server`` and the ``devpi`` tools are in beta status
because these are initial releases and more diverse real-life testing is
warranted.  The pre-0.9 releases of devpi-server already helped to iron 
out a number of issues and for the 0.9 transition a lot of effort went 
into making devpi-server work consistently with the new PyPI Content 
Delivery Network (CDN).

The project is actively developed and bound to see more releases in
2013, in particular in these areas:

- bugfixes and maintenance
- copying release files between index files and to pypi.python.org 
- better testing workflows
- mirroring between devpi-server instances

**One area that is lacking is the web UI**.  I am looking for a partner
to push forward with the web UI and design.  The server provides a 
nice evolving :doc:`REST API <curl>`.

Note that only part of the development is funded for a limited time.

You are very welcome to report issues, discuss or help:

* issues: https://bitbucket.org/hpk42/devpi/issues

* IRC: #pylib on irc.freenode.net.

* repository: https://bitbucket.org/hpk42/devpi

* mailing list: https://groups.google.com/d/forum/devpi-dev


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


Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`

