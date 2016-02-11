devpi-server: pypi server for caching and private indexes
=============================================================================

* `issue tracker <https://bitbucket.org/hpk42/devpi/issues>`_, `repo
  <https://bitbucket.org/hpk42/devpi>`_

* IRC: #devpi on freenode, `mailing list
  <https://groups.google.com/d/forum/devpi-dev>`_ 

* compatibility: {win,unix}-py{26,27,34}

consistent robust pypi-cache
----------------------------------------

You can point ``pip or easy_install`` to the ``root/pypi/+simple/``
index, serving as a self-updating transparent cache for pypi-hosted
**and** external packages.  Cache-invalidation uses the latest and
greatest PyPI protocols.  The cache index continues to serve when
offline and will resume cache-updates once network is available.

user specific indexes
---------------------

Each user (which can represent a person or a project, team) can have
multiple indexes and upload packages and docs via standard ``setup.py``
invocations command.  Users and indexes can be manipulated through a
RESTful HTTP API.

index inheritance
--------------------------

Each index can be configured to merge in other indexes so that it serves
both its uploads and all releases from other index(es).  For example, an
index using ``root/pypi`` as a parent is a good place to test out a
release candidate before you push it to PyPI.

good defaults and easy deployment
---------------------------------------

Get started easily and create a permanent devpi-server deployment
including pre-configured templates for ``nginx`` and cron. 

separate tool for Packaging/Testing activities
-------------------------------------------------------

The complimentary `devpi-client <http://pypi.python.org/devpi-client>`_ tool
helps to manage users, indexes, logins and typical setup.py-based upload and
installation workflows.

See http://doc.devpi.net for getting started and documentation.

