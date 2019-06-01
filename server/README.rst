=============================================================================
devpi-server: pypi server for caching and private indexes
=============================================================================

* `issue tracker <https://github.com/devpi/devpi/issues>`_, `repo
  <https://github.com/devpi/devpi>`_

* IRC: #devpi on freenode, `mailing list
  <https://mail.python.org/mm3/mailman3/lists/devpi-dev.python.org/>`_ 

* compatibility: {win,unix}-py{27,34,35,36,py}

consistent robust pypi-cache
============================

You can point ``pip or easy_install`` to the ``root/pypi/+simple/``
index, serving as a self-updating transparent cache for pypi-hosted
**and** external packages.  Cache-invalidation uses the latest and
greatest PyPI protocols.  The cache index continues to serve when
offline and will resume cache-updates once network is available.

user specific indexes
=====================

Each user (which can represent a person or a project, team) can have
multiple indexes and upload packages and docs via standard ``setup.py``
invocations command.  Users and indexes can be manipulated through a
RESTful HTTP API.

index inheritance
=================

Each index can be configured to merge in other indexes so that it serves
both its uploads and all releases from other index(es).  For example, an
index using ``root/pypi`` as a parent is a good place to test out a
release candidate before you push it to PyPI.

good defaults and easy deployment
=================================

Get started easily and create a permanent devpi-server deployment
including pre-configured templates for ``nginx`` and cron. 

separate tool for Packaging/Testing activities
==============================================

The complementary `devpi-client <https://pypi.org/project/devpi-client/>`_ tool
helps to manage users, indexes, logins and typical setup.py-based upload and
installation workflows.

See https://doc.devpi.net for getting started and documentation.


support
=======

If you find a bug, use the `issue tracker at Github`_.

For general questions use the #devpi IRC channel on `freenode.net`_ or the `devpi-dev@python.org mailing list`_.

For support contracts and paid help contact `merlinux.eu`_.

.. _issue tracker at Github: https://github.com/devpi/devpi/issues/
.. _freenode.net: https://freenode.net/
.. _devpi-dev@python.org mailing list: https://mail.python.org/mailman3/lists/devpi-dev.python.org/
.. _merlinux.eu: https://merlinux.eu
