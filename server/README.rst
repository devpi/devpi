=============================================================================
devpi-server: server for private package indexes and PyPI caching
=============================================================================


PyPI cache
==========

You can point ``pip or easy_install`` to the ``root/pypi/+simple/``
index, serving as a transparent cache for pypi-hosted packages.


User specific indexes
=====================

Each user (which can represent a person, project or team) can have
multiple indexes and upload packages and docs via standard ``twine`` or
``setup.py`` invocations.  Users and indexes can be manipulated through
`devpi-client`_ and a RESTful HTTP API.


Index inheritance
=================

Each index can be configured to merge in other indexes so that it serves
both its uploads and all releases from other index(es).  For example, an
index using ``root/pypi`` as a parent is a good place to test out a
release candidate before you push it to PyPI.


Good defaults and easy deployment
=================================

Get started easily and create a permanent devpi-server deployment
including pre-configured templates for ``nginx`` and process managers.


Separate tool for Packaging/Testing activities
==============================================

The complementary `devpi-client`_ tool
helps to manage users, indexes, logins and typical setup.py-based upload and
installation workflows.

See https://doc.devpi.net on how to get started and further documentation.


.. _devpi-client: https://pypi.org/project/devpi-client/


Support
=======

If you find a bug, use the `issue tracker at Github`_.

For general questions use `GitHub Discussions`_ or the `devpi-dev@python.org mailing list`_.

For support contracts and paid help contact ``mail at pyfidelity.com``.

.. _issue tracker at Github: https://github.com/devpi/devpi/issues/
.. _devpi-dev@python.org mailing list: https://mail.python.org/mailman3/lists/devpi-dev.python.org/
.. _GitHub Discussions: https://github.com/devpi/devpi/discussions
